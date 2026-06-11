#!/usr/bin/env bats
# Tests for actions/check-token-health/check_token_health.sh
# Uses mock curl to exercise each code path without real GitHub API calls.

SCRIPT="${BATS_TEST_DIRNAME}/../../actions/check-token-health/check_token_health.sh"

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  # Default env vars (override per test as needed)
  export GH_TOKEN="ghp_test_token"
  export TOKEN_NAME="TEST_TOKEN"
  export REQUIRED_SCOPES=""
  export MIN_REMAINING="100"

  # Put mock directory first on PATH
  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  # Default auth-response.json (no expiry)
  export AUTH_RESPONSE_FILE="${TEST_TMP}/auth-response.json"
  echo '{"login":"testuser"}' > "$AUTH_RESPONSE_FILE"

  # Default rate-limit response
  export RATE_LIMIT_JSON='{"rate":{"remaining":5000,"reset":9999999999}}'
  export SCOPES_RESPONSE="repo, workflow"
}

# Helper: install a mock curl that returns $1 HTTP code for user endpoint
# and $2 scopes header; optional $3 for rate_limit JSON override
# Pass empty string "" for $2 to simulate a fine-grained PAT (no scopes header).
make_curl_mock() {
  local http_code="${1:-200}"
  # Use explicit check (not :-) so empty string "" is preserved, not replaced by default
  local scopes; [ "$#" -ge 2 ] && scopes="$2" || scopes="repo, workflow"
  local rate_json="${3:-${RATE_LIMIT_JSON}}"

  cat > "${MOCK_DIR}/curl" <<MOCK
#!/usr/bin/env bash
# Mock curl
args=("\$@")
url="\${args[-1]}"

if [[ "\$*" == *"-o /tmp/auth-response.json"* ]]; then
  # Auth check request — write auth response and return HTTP code
  cp "${AUTH_RESPONSE_FILE}" /tmp/auth-response.json
  printf '%s' "${http_code}"
elif [[ "\$*" == *"-I"* ]] && [[ "\$url" == *"api.github.com/user"* ]]; then
  # Headers request for scope check
  printf 'HTTP/2 200\r\nx-oauth-scopes: ${scopes}\r\n\r\n'
elif [[ "\$url" == *"rate_limit"* ]]; then
  # Rate limit request
  printf '%s' '${rate_json}'
fi
MOCK
  chmod +x "${MOCK_DIR}/curl"
}

teardown() {
  rm -rf "$TEST_TMP"
}

# ── HTTP 200 — valid token, no required scopes ────────────────────────────────

@test "valid token passes with no required scopes" {
  make_curl_mock 200 "repo, workflow"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "valid=true" "$GITHUB_OUTPUT"
  grep -q "rate_remaining=5000" "$GITHUB_OUTPUT"
  grep -q "expires_at=none" "$GITHUB_OUTPUT"
}

# ── HTTP 401 — expired/revoked token ─────────────────────────────────────────

@test "HTTP 401 sets valid=false and exits 1" {
  make_curl_mock 401
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  grep -q "valid=false" "$GITHUB_OUTPUT"
  [[ "$output" == *"invalid or expired"* ]]
}

# ── HTTP 403 — suspended/IP-blocked ──────────────────────────────────────────

@test "HTTP 403 sets valid=false and exits 1" {
  make_curl_mock 403
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  grep -q "valid=false" "$GITHUB_OUTPUT"
  [[ "$output" == *"forbidden"* ]]
}

# ── Other non-200 HTTP ────────────────────────────────────────────────────────

@test "HTTP 500 sets valid=false and exits 1" {
  make_curl_mock 500
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  grep -q "valid=false" "$GITHUB_OUTPUT"
}

# ── Scope verification ────────────────────────────────────────────────────────

@test "token with required scope passes" {
  make_curl_mock 200 "repo, workflow"
  export REQUIRED_SCOPES="repo"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "valid=true" "$GITHUB_OUTPUT"
}

@test "token with multiple required scopes passes when all present" {
  make_curl_mock 200 "repo, workflow, admin:org"
  export REQUIRED_SCOPES="repo,workflow"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "valid=true" "$GITHUB_OUTPUT"
}

@test "token missing required scope fails" {
  # Use "public_repo" scopes but require "workflow" — workflow is NOT a substring of public_repo
  make_curl_mock 200 "public_repo"
  export REQUIRED_SCOPES="workflow"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  grep -q "valid=false" "$GITHUB_OUTPUT"
  [[ "$output" == *"missing required scope"* ]]
}

@test "fine-grained PAT with no scopes header and no required scopes passes" {
  # Fine-grained PATs return empty x-oauth-scopes header
  make_curl_mock 200 ""
  export REQUIRED_SCOPES=""
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "valid=true" "$GITHUB_OUTPUT"
}

@test "fine-grained PAT with no scopes header fails when scopes required" {
  make_curl_mock 200 ""
  export REQUIRED_SCOPES="repo"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  grep -q "valid=false" "$GITHUB_OUTPUT"
}

# ── Rate limit warning ────────────────────────────────────────────────────────

@test "rate limit warning emitted when remaining below threshold" {
  make_curl_mock 200 "repo" '{"rate":{"remaining":50,"reset":9999999999}}'
  export MIN_REMAINING="100"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]  # still valid, just a warning
  grep -q "valid=true" "$GITHUB_OUTPUT"
  [[ "$output" == *"rate limit low"* ]]
}

@test "no rate limit warning when remaining above threshold" {
  make_curl_mock 200 "repo" '{"rate":{"remaining":5000,"reset":9999999999}}'
  export MIN_REMAINING="100"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" != *"rate limit low"* ]]
}

# ── Token expiry detection ────────────────────────────────────────────────────

@test "token with expiry sets expires_at output" {
  echo '{"login":"testuser","expires_at":"2026-12-31T00:00:00Z"}' > "$AUTH_RESPONSE_FILE"
  make_curl_mock 200 "repo"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "expires_at=2026-12-31T00:00:00Z" "$GITHUB_OUTPUT"
}

@test "token without expiry sets expires_at=none" {
  echo '{"login":"testuser"}' > "$AUTH_RESPONSE_FILE"
  make_curl_mock 200 "repo"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "expires_at=none" "$GITHUB_OUTPUT"
}
