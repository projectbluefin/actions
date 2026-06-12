#!/usr/bin/env bats
# Tests for scripts/resolve_digests.sh
# Covers: successful resolution, partial failure, empty variants, object variant
# format, digests JSON correctness, rows output, ok/summary values.

SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/resolve_digests.sh"

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  # Default env vars
  export REGISTRY="ghcr.io/projectbluefin"
  export TARGET_TAG="testing"
  export VARIANTS_JSON='["bluefin"]'
}

teardown() {
  rm -rf "$TEST_TMP"
}

# Helper: mock skopeo that always returns a fixed digest
make_skopeo_success() {
  local digest="${1:-sha256:abc123def456}"
  cat > "${MOCK_DIR}/skopeo" <<EOF
#!/usr/bin/env bash
echo "${digest}"
EOF
  chmod +x "${MOCK_DIR}/skopeo"
}

# Helper: mock skopeo that always fails
make_skopeo_fail() {
  cat > "${MOCK_DIR}/skopeo" <<'EOF'
#!/usr/bin/env bash
echo "manifest unknown" >&2
exit 1
EOF
  chmod +x "${MOCK_DIR}/skopeo"
}

# Helper: extract a single-line output value from GITHUB_OUTPUT
get_output() {
  local key="$1"
  grep "^${key}=" "$GITHUB_OUTPUT" | head -1 | cut -d= -f2-
}

# ── Successful resolution ──────────────────────────────────────────────────────

@test "single string variant resolves → ok=true" {
  make_skopeo_success "sha256:abc123def456"
  export VARIANTS_JSON='["bluefin"]'
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output ok)" = "true" ]
}

@test "summary mentions count and tag on success" {
  make_skopeo_success "sha256:abc123"
  export VARIANTS_JSON='["bluefin"]'
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  summary=$(get_output summary)
  [[ "$summary" == *"1"* ]]
  [[ "$summary" == *"testing"* ]]
}

@test "digests JSON maps image to resolved digest" {
  make_skopeo_success "sha256:deadbeef"
  export VARIANTS_JSON='["bluefin"]'
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  digests=$(get_output digests)
  echo "$digests" | jq -e '.bluefin == "sha256:deadbeef"'
}

@test "rows output contains image and digest" {
  make_skopeo_success "sha256:deadbeef"
  export VARIANTS_JSON='["bluefin"]'
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$(<"$GITHUB_OUTPUT")" == *"bluefin|sha256:deadbeef"* ]]
}

@test "multiple string variants all resolve → ok=true" {
  make_skopeo_success "sha256:multiabc"
  export VARIANTS_JSON='["bluefin", "bluefin-dx"]'
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output ok)" = "true" ]
  digests=$(get_output digests)
  echo "$digests" | jq -e '.["bluefin-dx"] == "sha256:multiabc"'
}

@test "object variant with .image key resolves correctly" {
  make_skopeo_success "sha256:obj123"
  export VARIANTS_JSON='[{"image": "bluefin-hwe", "extra": "ignored"}]'
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output ok)" = "true" ]
  digests=$(get_output digests)
  echo "$digests" | jq -e '.["bluefin-hwe"] == "sha256:obj123"'
}

# ── Failure paths ─────────────────────────────────────────────────────────────

@test "skopeo failure → ok=false" {
  make_skopeo_fail
  export VARIANTS_JSON='["bluefin"]'
  run bash "$SCRIPT"
  # Script exits 0 — ok= captures the result, not the exit code
  [ "$status" -eq 0 ]
  [ "$(get_output ok)" = "false" ]
}

@test "failed variant appears in rows as ERROR" {
  make_skopeo_fail
  export VARIANTS_JSON='["bluefin"]'
  run bash "$SCRIPT"
  [[ "$(<"$GITHUB_OUTPUT")" == *"bluefin|ERROR"* ]]
}

@test "partial failure (first ok, second fails) → ok=false" {
  CALL_COUNT_FILE="${TEST_TMP}/calls"
  echo "0" > "$CALL_COUNT_FILE"
  # Unquoted heredoc so ${CALL_COUNT_FILE} expands at write-time; \$count is literal
  cat > "${MOCK_DIR}/skopeo" <<EOF
#!/usr/bin/env bash
count=\$(cat ${CALL_COUNT_FILE})
count=\$((count + 1))
echo \$count > ${CALL_COUNT_FILE}
if [ "\$count" -eq 1 ]; then
  echo "sha256:first"
else
  exit 1
fi
EOF
  chmod +x "${MOCK_DIR}/skopeo"
  export VARIANTS_JSON='["bluefin", "bluefin-dx"]'
  run bash "$SCRIPT"
  [ "$(get_output ok)" = "false" ]
  # First variant should still be in digests
  digests=$(get_output digests)
  echo "$digests" | jq -e '.bluefin == "sha256:first"'
}

# ── Edge cases ─────────────────────────────────────────────────────────────────

@test "empty VARIANTS_JSON array → ok=true with empty digests object" {
  make_skopeo_success "sha256:unused"
  export VARIANTS_JSON='[]'
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output ok)" = "true" ]
  [ "$(get_output digests)" = "{}" ]
}
