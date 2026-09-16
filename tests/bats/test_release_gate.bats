#!/usr/bin/env bats
# Tests for scripts/resolve_digests.sh and scripts/verify_signatures.sh
# Exercises: successful resolution, partial failure, cosign pass/fail,
# skipped verification on failed resolution, and missing digest handling.

setup() {
  RESOLVE_SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/resolve_digests.sh"
  VERIFY_SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/verify_signatures.sh"
  E2E_SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/check_e2e_status.sh"
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  # Default env for resolve
  export REGISTRY="ghcr.io/projectbluefin"
  export TARGET_TAG="testing"
  export VARIANTS_JSON='["bluefin", "bluefin-nvidia"]'
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

# ── Digest resolution ─────────────────────────────────────────────────────────

make_skopeo_mock() {
  local mode="${1:-success}"  # success | fail | partial
  cat > "${MOCK_DIR}/skopeo" <<SKOPEO
#!/usr/bin/env bash
# mode: ${mode}
image="\${@: -1}"  # last arg is the image ref
case "${mode}" in
  success)
    echo "sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abcd"
    ;;
  fail)
    echo "error: manifest unknown" >&2
    exit 1
    ;;
  partial)
    if [[ "\$image" == *"nvidia"* ]]; then
      echo "error: not found" >&2
      exit 1
    fi
    echo "sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abcd"
    ;;
esac
SKOPEO
  chmod +x "${MOCK_DIR}/skopeo"
}

@test "resolve: all variants succeed → ok=true" {
  make_skopeo_mock success
  run bash "$RESOLVE_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=true" "$GITHUB_OUTPUT"
  grep -q "^summary=Resolved 2" "$GITHUB_OUTPUT"
}

@test "resolve: digests JSON contains both images" {
  make_skopeo_mock success
  run bash "$RESOLVE_SCRIPT"
  [ "$status" -eq 0 ]
  digests=$(get_output digests)
  echo "$digests" | jq -e '.["bluefin"]' >/dev/null
  echo "$digests" | jq -e '.["bluefin-nvidia"]' >/dev/null
}

@test "resolve: all fail → ok=false" {
  make_skopeo_mock fail
  run bash "$RESOLVE_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=false" "$GITHUB_OUTPUT"
  grep -q "Failed to resolve" "$GITHUB_OUTPUT"
}

@test "resolve: partial failure → ok=false" {
  make_skopeo_mock partial
  run bash "$RESOLVE_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=false" "$GITHUB_OUTPUT"
}

@test "resolve: single string variant" {
  export VARIANTS_JSON='["bluefin"]'
  make_skopeo_mock success
  run bash "$RESOLVE_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "Resolved 1" "$GITHUB_OUTPUT"
}

@test "resolve: object variant with 'image' key" {
  export VARIANTS_JSON='[{"image": "bluefin"}]'
  make_skopeo_mock success
  run bash "$RESOLVE_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=true" "$GITHUB_OUTPUT"
}

@test "resolve: empty variants list → ok=true with 0 resolved" {
  export VARIANTS_JSON='[]'
  make_skopeo_mock success
  run bash "$RESOLVE_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=true" "$GITHUB_OUTPUT"
  grep -q "Resolved 0" "$GITHUB_OUTPUT"
}

# ── Signature verification ────────────────────────────────────────────────────

make_cosign_mock() {
  local mode="${1:-pass}"  # pass | fail | partial
  cat > "${MOCK_DIR}/cosign" <<COSIGN
#!/usr/bin/env bash
# mode: ${mode}
ref="\${@: -1}"  # last arg is the image ref
case "${mode}" in
  pass)
    exit 0
    ;;
  fail)
    echo "error: no matching signatures" >&2
    exit 1
    ;;
  partial)
    if [[ "\$ref" == *"nvidia"* ]]; then
      echo "error: no matching signatures" >&2
      exit 1
    fi
    exit 0
    ;;
esac
COSIGN
  chmod +x "${MOCK_DIR}/cosign"
}

@test "verify: all pass when resolve succeeded and cosign verifies" {
  make_cosign_mock pass
  export RESOLVE_OK="true"
  export DIGESTS_JSON='{"bluefin":"sha256:abc","bluefin-nvidia":"sha256:def"}'
  export IDENTITY_REGEXP="https://github.com/projectbluefin/.*"
  export GITHUB_OUTPUT="${TEST_TMP}/github_output2"
  touch "$GITHUB_OUTPUT"
  run bash "$VERIFY_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=true" "$GITHUB_OUTPUT"
}

@test "verify: skipped when resolve_ok=false" {
  export RESOLVE_OK="false"
  export DIGESTS_JSON='{}'
  export IDENTITY_REGEXP=".*"
  export GITHUB_OUTPUT="${TEST_TMP}/github_output2"
  touch "$GITHUB_OUTPUT"
  run bash "$VERIFY_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=false" "$GITHUB_OUTPUT"
  grep -q "Skipped" "$GITHUB_OUTPUT"
}

@test "verify: all fail when cosign fails" {
  make_cosign_mock fail
  export RESOLVE_OK="true"
  export DIGESTS_JSON='{"bluefin":"sha256:abc","bluefin-nvidia":"sha256:def"}'
  export IDENTITY_REGEXP=".*"
  export GITHUB_OUTPUT="${TEST_TMP}/github_output2"
  touch "$GITHUB_OUTPUT"
  run bash "$VERIFY_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=false" "$GITHUB_OUTPUT"
}

@test "verify: partial failure → ok=false" {
  make_cosign_mock partial
  export RESOLVE_OK="true"
  export DIGESTS_JSON='{"bluefin":"sha256:abc","bluefin-nvidia":"sha256:def"}'
  export IDENTITY_REGEXP=".*"
  export GITHUB_OUTPUT="${TEST_TMP}/github_output2"
  touch "$GITHUB_OUTPUT"
  run bash "$VERIFY_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=false" "$GITHUB_OUTPUT"
  results=$(grep "^results=" "$GITHUB_OUTPUT" | cut -d= -f2-)
  echo "$results" | jq -e '.["bluefin"] == "passed"' >/dev/null
  echo "$results" | jq -e '.["bluefin-nvidia"] == "failed"' >/dev/null
}

@test "verify: missing digest in DIGESTS_JSON → image fails" {
  make_cosign_mock pass
  export RESOLVE_OK="true"
  export DIGESTS_JSON='{"bluefin":"sha256:abc"}'  # bluefin-nvidia missing
  export IDENTITY_REGEXP=".*"
  export GITHUB_OUTPUT="${TEST_TMP}/github_output2"
  touch "$GITHUB_OUTPUT"
  run bash "$VERIFY_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^ok=false" "$GITHUB_OUTPUT"
  results=$(grep "^results=" "$GITHUB_OUTPUT" | cut -d= -f2-)
  echo "$results" | jq -e '.["bluefin-nvidia"] == "failed"' >/dev/null
}

# ── Commit-bound E2E status ──────────────────────────────────────────────────

make_gh_status_mock() {
  cat > "${MOCK_DIR}/gh" <<'GH'
#!/usr/bin/env bash
printf '%s\n' "$STATUS_RESPONSE"
GH
  chmod +x "${MOCK_DIR}/gh"
}

prepare_e2e_check() {
  make_gh_status_mock
  export RUN_E2E="true"
  export E2E_IMAGE="ghcr.io/projectbluefin/bluefin:testing"
  export E2E_STATUS_CONTEXT="e2e/post-testing"
  export E2E_SUITES="smoke,common"
  export HEAD_SHA="0123456789abcdef0123456789abcdef01234567"
  export REPO="projectbluefin/bluefin"
  export GITHUB_OUTPUT="${TEST_TMP}/e2e_output"
  touch "$GITHUB_OUTPUT"
}

@test "e2e: matching successful commit status passes" {
  prepare_e2e_check
  export STATUS_RESPONSE='{"statuses":[{"context":"e2e/post-testing","state":"success","updated_at":"2026-09-16T12:00:00Z","target_url":"https://example.test/run/1"}]}'
  run bash "$E2E_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q '^ok=true' "$GITHUB_OUTPUT"
  grep -q '^last_status=success' "$GITHUB_OUTPUT"
}

@test "e2e: status for a different context does not qualify" {
  prepare_e2e_check
  export STATUS_RESPONSE='{"statuses":[{"context":"ci/build","state":"success","updated_at":"2026-09-16T12:00:00Z"}]}'
  run bash "$E2E_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q '^ok=false' "$GITHUB_OUTPUT"
  grep -q '^last_status=missing' "$GITHUB_OUTPUT"
}

@test "e2e: matching failed commit status blocks promotion" {
  prepare_e2e_check
  export STATUS_RESPONSE='{"statuses":[{"context":"e2e/post-testing","state":"failure","updated_at":"2026-09-16T12:00:00Z","target_url":"https://example.test/run/2"}]}'
  run bash "$E2E_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q '^ok=false' "$GITHUB_OUTPUT"
  grep -q '^last_status=failure' "$GITHUB_OUTPUT"
}

@test "e2e: disabled gate skips without querying GitHub" {
  prepare_e2e_check
  export RUN_E2E="false"
  rm "${MOCK_DIR}/gh"
  run bash "$E2E_SCRIPT"
  [ "$status" -eq 0 ]
  grep -q '^ok=true' "$GITHUB_OUTPUT"
  grep -q '^state=skipped' "$GITHUB_OUTPUT"
}
