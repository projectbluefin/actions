#!/usr/bin/env bats
# Tests for scripts/verify_signatures.sh
# Covers: RESOLVE_OK short-circuit, successful verification, failed verification,
# missing digest, object variant format, partial failure, output variable correctness.

SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/verify_signatures.sh"

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  # Default env vars
  export REGISTRY="ghcr.io/projectbluefin"
  export VARIANTS_JSON='["bluefin"]'
  export DIGESTS_JSON='{"bluefin": "sha256:abc123"}'
  export IDENTITY_REGEXP="https://github.com/projectbluefin/bluefin/.*"
  export RESOLVE_OK="true"
}

teardown() {
  rm -rf "$TEST_TMP"
}

# Helper: mock cosign that always succeeds
make_cosign_success() {
  cat > "${MOCK_DIR}/cosign" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "${MOCK_DIR}/cosign"
}

# Helper: mock cosign that always fails
make_cosign_fail() {
  cat > "${MOCK_DIR}/cosign" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
  chmod +x "${MOCK_DIR}/cosign"
}

# Helper: extract a single-line output value from GITHUB_OUTPUT
get_output() {
  local key="$1"
  grep "^${key}=" "$GITHUB_OUTPUT" | head -1 | cut -d= -f2-
}

# ── RESOLVE_OK short-circuit ──────────────────────────────────────────────────

@test "RESOLVE_OK=false skips cosign and sets ok=false" {
  make_cosign_success  # cosign would succeed, but must not be called
  export RESOLVE_OK="false"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output ok)" = "false" ]
}

@test "RESOLVE_OK=false summary mentions Skipped" {
  make_cosign_success
  export RESOLVE_OK="false"
  run bash "$SCRIPT"
  summary=$(get_output summary)
  [[ "$summary" == *"Skipped"* ]]
}

@test "RESOLVE_OK=false writes empty results object" {
  make_cosign_success
  export RESOLVE_OK="false"
  run bash "$SCRIPT"
  [ "$(get_output results)" = "{}" ]
}

# ── Successful verification ───────────────────────────────────────────────────

@test "all signatures pass → ok=true" {
  make_cosign_success
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output ok)" = "true" ]
}

@test "successful verification maps image to 'passed' in results" {
  make_cosign_success
  run bash "$SCRIPT"
  results=$(get_output results)
  echo "$results" | jq -e '.bluefin == "passed"'
}

@test "rows shows 'passed|signature verified' for verified image" {
  make_cosign_success
  run bash "$SCRIPT"
  [[ "$(<"$GITHUB_OUTPUT")" == *"bluefin|passed|signature verified"* ]]
}

@test "multiple variants all pass → ok=true" {
  make_cosign_success
  export VARIANTS_JSON='["bluefin", "bluefin-dx"]'
  export DIGESTS_JSON='{"bluefin": "sha256:aaa", "bluefin-dx": "sha256:bbb"}'
  run bash "$SCRIPT"
  [ "$(get_output ok)" = "true" ]
  results=$(get_output results)
  echo "$results" | jq -e '.["bluefin-dx"] == "passed"'
}

# ── Failed verification ───────────────────────────────────────────────────────

@test "cosign failure → ok=false" {
  make_cosign_fail
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output ok)" = "false" ]
}

@test "failed verification maps image to 'failed' in results" {
  make_cosign_fail
  run bash "$SCRIPT"
  results=$(get_output results)
  echo "$results" | jq -e '.bluefin == "failed"'
}

@test "rows shows 'failed|signature verification failed'" {
  make_cosign_fail
  run bash "$SCRIPT"
  [[ "$(<"$GITHUB_OUTPUT")" == *"bluefin|failed|signature verification failed"* ]]
}

# ── Missing digest edge case ──────────────────────────────────────────────────

@test "missing digest in DIGESTS_JSON → ok=false" {
  make_cosign_success  # cosign should not be reached
  export VARIANTS_JSON='["bluefin"]'
  export DIGESTS_JSON='{}'
  run bash "$SCRIPT"
  [ "$(get_output ok)" = "false" ]
}

@test "missing digest maps image to 'failed' in results" {
  make_cosign_success
  export VARIANTS_JSON='["bluefin"]'
  export DIGESTS_JSON='{}'
  run bash "$SCRIPT"
  results=$(get_output results)
  echo "$results" | jq -e '.bluefin == "failed"'
}

@test "rows shows 'digest missing' for missing digest" {
  make_cosign_success
  export VARIANTS_JSON='["bluefin"]'
  export DIGESTS_JSON='{}'
  run bash "$SCRIPT"
  [[ "$(<"$GITHUB_OUTPUT")" == *"bluefin|failed|digest missing"* ]]
}

# ── Object variant format ─────────────────────────────────────────────────────

@test "object variant with .image key verifies correctly" {
  make_cosign_success
  export VARIANTS_JSON='[{"image": "bluefin-hwe"}]'
  export DIGESTS_JSON='{"bluefin-hwe": "sha256:obj123"}'
  run bash "$SCRIPT"
  [ "$(get_output ok)" = "true" ]
  results=$(get_output results)
  echo "$results" | jq -e '.["bluefin-hwe"] == "passed"'
}

# ── Partial failure ───────────────────────────────────────────────────────────

@test "partial cosign failure (first passes, second fails) → ok=false" {
  CALL_COUNT_FILE="${TEST_TMP}/calls"
  echo "0" > "$CALL_COUNT_FILE"
  # Unquoted heredoc: ${CALL_COUNT_FILE} expands at write-time; \$count is literal
  cat > "${MOCK_DIR}/cosign" <<EOF
#!/usr/bin/env bash
count=\$(cat ${CALL_COUNT_FILE})
count=\$((count + 1))
echo \$count > ${CALL_COUNT_FILE}
[ "\$count" -eq 1 ]
EOF
  chmod +x "${MOCK_DIR}/cosign"
  export VARIANTS_JSON='["bluefin", "bluefin-dx"]'
  export DIGESTS_JSON='{"bluefin": "sha256:aaa", "bluefin-dx": "sha256:bbb"}'
  run bash "$SCRIPT"
  [ "$(get_output ok)" = "false" ]
  results=$(get_output results)
  echo "$results" | jq -e '.bluefin == "passed"'
  echo "$results" | jq -e '.["bluefin-dx"] == "failed"'
}
