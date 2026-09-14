#!/usr/bin/env bats
# Tests for bootc-build/dnf-cache inline shell logic.
#
# The shell logic lives inline in bootc-build/dnf-cache/action.yml
# in the "Fix cache permissions before save" step.
# The snippet below is a verbatim copy of that run block so this test breaks
# if the action logic changes without updating the test.
#
# Covers:
#   - chmod 777 --recursive applied to matching directories (/var/tmp/buildah-cache-*)
#   - non-matching patterns or nonexistent directories do not fail (handled cleanly)
#   - regular files matching the pattern are not chmod'd (test is `-d`)
#   - multiple matching directories all receive chmod
#   - chmod failure propagates non-zero status
#   - snippet drift guard against action.yml

CACHE_PERMS_SNIPPET=$(cat <<'SNIP'
set -euo pipefail
for d in "${CACHE_BASE}"/buildah-cache-*; do
  if [[ -d "$d" ]]; then
    sudo chmod 777 --recursive "$d"
  fi
done
SNIP
)

setup() {
  TEST_TMP=$(mktemp -d)
  export TEST_TMP
  export CACHE_BASE="${TEST_TMP}/cache_root"
  mkdir -p "$CACHE_BASE"

  export STUB_BIN="${TEST_TMP}/bin"
  mkdir -p "$STUB_BIN"
  export CMD_LOG="${TEST_TMP}/cmd.log"
  : >"$CMD_LOG"

  # Stub sudo to run the command and log
  cat >"${STUB_BIN}/sudo" <<'STUB'
#!/usr/bin/env bash
echo "sudo $*" >>"$CMD_LOG"
"$@"
STUB
  chmod +x "${STUB_BIN}/sudo"

  # Stub chmod to log
  cat >"${STUB_BIN}/chmod" <<'STUB'
#!/usr/bin/env bash
echo "chmod $*" >>"$CMD_LOG"
if [[ "${CHMOD_FAIL:-0}" == "1" ]]; then
  echo "chmod failed" >&2
  exit 1
fi
exit 0
STUB
  chmod +x "${STUB_BIN}/chmod"

  export PATH="${STUB_BIN}:${PATH}"
}

teardown() {
  rm -rf "$TEST_TMP"
}

# ── Directory permissions fix ─────────────────────────────────────────────────

@test "dnf-cache perms: matching directory receives sudo chmod 777 --recursive" {
  mkdir -p "${CACHE_BASE}/buildah-cache-bluefin"
  run bash -c "$CACHE_PERMS_SNIPPET"
  [ "$status" -eq 0 ]

  run grep "sudo chmod 777 --recursive ${CACHE_BASE}/buildah-cache-bluefin" "$CMD_LOG"
  [ "$status" -eq 0 ]
}

@test "dnf-cache perms: multiple matching directories all receive chmod" {
  mkdir -p "${CACHE_BASE}/buildah-cache-1"
  mkdir -p "${CACHE_BASE}/buildah-cache-2"
  run bash -c "$CACHE_PERMS_SNIPPET"
  [ "$status" -eq 0 ]

  run grep "sudo chmod 777 --recursive ${CACHE_BASE}/buildah-cache-1" "$CMD_LOG"
  [ "$status" -eq 0 ]
  run grep "sudo chmod 777 --recursive ${CACHE_BASE}/buildah-cache-2" "$CMD_LOG"
  [ "$status" -eq 0 ]
}

@test "dnf-cache perms: no matching directories silently succeeds without chmod invocation" {
  # Unexpanded glob won't match -d
  run bash -c "$CACHE_PERMS_SNIPPET"
  [ "$status" -eq 0 ]

  run grep "chmod" "$CMD_LOG"
  [ "$status" -ne 0 ]
}

@test "dnf-cache perms: regular file matching pattern is ignored" {
  touch "${CACHE_BASE}/buildah-cache-file"
  run bash -c "$CACHE_PERMS_SNIPPET"
  [ "$status" -eq 0 ]

  run grep "chmod" "$CMD_LOG"
  [ "$status" -ne 0 ]
}

@test "dnf-cache perms: chmod failure propagates non-zero exit code" {
  mkdir -p "${CACHE_BASE}/buildah-cache-fail"
  export CHMOD_FAIL="1"
  run bash -c "$CACHE_PERMS_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"chmod failed"* ]]
}

# ── Snippet drift guard ───────────────────────────────────────────────────────

@test "dnf-cache: action.yml still contains the chmod permission fix under test" {
  ACTION="${BATS_TEST_DIRNAME}/../../bootc-build/dnf-cache/action.yml"
  [ -f "$ACTION" ]
  grep -Fq 'for d in /var/tmp/buildah-cache-*; do' "$ACTION"
  grep -Fq 'sudo chmod 777 --recursive "$d"' "$ACTION"
}
