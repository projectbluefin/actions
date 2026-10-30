#!/usr/bin/env bats
# Regression tests for the chunka action's chunkah pull retry loop (issue #663).
#
# The retry loop lives inline in bootc-build/chunka/action.yml. It is extracted
# from that file at setup time (CHUNKAH_PULL_LOOP) so an edit to the action that
# changes the retry behavior is tested exactly as written — the test cannot
# silently drift from the code it guards. (The config-file fix in
# test_chunka.bats has its own setup(); this file is a focused companion.)
#
# Covers:
#   - All three pulls fail → exits non-zero with ::error::, before any podman run
#   - The exhausted loop issues exactly three pulls and never reaches the run step
#   - Pull succeeds on the first attempt → exits 0
#   - Pull fails twice, succeeds on the third → retries still work, exits 0

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  # Mock sudo: pass-through (no privilege needed in tests)
  cat > "${MOCK_DIR}/sudo" << 'EOF'
#!/usr/bin/env bash
"$@"
EOF
  chmod +x "${MOCK_DIR}/sudo"

  # Mock sleep: no-op (don't actually wait between retries)
  cat > "${MOCK_DIR}/sleep" << 'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "${MOCK_DIR}/sleep"

  # Track podman invocations so tests can assert what the loop reached.
  export PODMAN_CALL_LOG="${TEST_TMP}/podman_calls"
  touch "$PODMAN_CALL_LOG"

  # Default podman stub: always fails the pull (the bug being guarded).
  cat > "${MOCK_DIR}/podman" << 'EOF'
#!/usr/bin/env bash
echo "podman $*" >> "${PODMAN_CALL_LOG}"
exit 1
EOF
  chmod +x "${MOCK_DIR}/podman"

  export CHUNKAH_REF="quay.io/coreos/chunkah:test@sha256:deadbeef"

  # Extract the `for attempt in 1 2 3; do ... done` block verbatim from the
  # action so the test runs exactly what ships.
  CHUNKAH_PULL_LOOP="$(awk '/for attempt in 1 2 3; do/{f=1} f{print} f&&/^ *done$/{exit}' "${BATS_TEST_DIRNAME}/../../bootc-build/chunka/action.yml")"
}

teardown() {
  rm -rf "${TEST_TMP:-}"
}

# Run the extracted loop the way the action does: with set -euo pipefail in force,
# followed by a sentinel standing in for the code after the loop (the podman run
# step and everything past it). The bug is a fall-through: the old loop reached the
# sentinel and kept building. The fix must not.
run_pull_loop() {
  local script="${TEST_TMP}/pull_loop.sh"
  { echo "set -euo pipefail"; echo "${CHUNKAH_PULL_LOOP}"; echo 'echo PAST_LOOP_SENTINEL'; } > "$script"
  run bash "$script"
}

pull_count() {
  grep -c '^podman pull' "${PODMAN_CALL_LOG}"
}

# ── Failure path (the bug this guards) ────────────────────────────────────────

@test "all three pulls fail → non-zero exit and ::error:: message" {
  run_pull_loop
  [ "$status" -ne 0 ]
  [[ "$output" == *"chunkah pull failed after 3 attempts"* ]]
}

@test "exhausted pulls stop before the code after the loop (no fall-through)" {
  run_pull_loop
  [ "$status" -ne 0 ]
  [[ "$output" != *"PAST_LOOP_SENTINEL"* ]]
}

@test "exhausted pulls issue exactly three attempts, not more" {
  run_pull_loop
  [ "$(pull_count)" -eq 3 ]
}

@test "exhausted pulls never reach the podman run step that follows the loop" {
  run_pull_loop
  [ "$status" -ne 0 ]
  ! grep -q '^podman run' "${PODMAN_CALL_LOG}"
}

# ── Success paths (retries must still work) ───────────────────────────────────

@test "pull succeeds on first attempt → exit 0 after one pull" {
  cat > "${MOCK_DIR}/podman" << 'EOF'
#!/usr/bin/env bash
echo "podman $*" >> "${PODMAN_CALL_LOG}"
if [[ "$1" == "pull" ]]; then exit 0; fi
exit 1
EOF
  chmod +x "${MOCK_DIR}/podman"

  run_pull_loop
  [ "$status" -eq 0 ]
  [ "$(pull_count)" -eq 1 ]
}

@test "pull fails twice then succeeds on the third → exit 0" {
  cat > "${MOCK_DIR}/podman" << EOF
#!/usr/bin/env bash
echo "podman \$*" >> "${PODMAN_CALL_LOG}"
if [[ "\$1" == "pull" ]]; then
  n=\$(cat "${TEST_TMP}/pull_count" 2>/dev/null || echo 0)
  n=\$((n + 1))
  echo "\$n" > "${TEST_TMP}/pull_count"
  [[ \$n -ge 3 ]] && exit 0
fi
exit 1
EOF
  chmod +x "${MOCK_DIR}/podman"

  run_pull_loop
  [ "$status" -eq 0 ]
  [ "$(pull_count)" -eq 3 ]
}
