#!/usr/bin/env bash
# Extracted from actions/check-token-health/action.yml — called by action.yml step.
# All inputs are passed as environment variables (see action.yml env: block).
#
# Required env vars:
#   GH_TOKEN          - the GitHub token to validate
#   TOKEN_NAME        - human-readable name for error messages
#   REQUIRED_SCOPES   - comma-separated required OAuth scopes (empty = skip check)
#   MIN_REMAINING     - minimum API requests remaining before warning

set -euo pipefail

# 1. Basic auth check
HTTP_CODE=$(curl -s -o /tmp/auth-response.json -w '%{http_code}' \
  -H "Authorization: Bearer ${GH_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/user)

if [ "$HTTP_CODE" = "401" ]; then
  echo "::error::Token '${TOKEN_NAME}' is invalid or expired (HTTP 401)"
  echo "valid=false" >> "$GITHUB_OUTPUT"
  exit 1
elif [ "$HTTP_CODE" = "403" ]; then
  echo "::error::Token '${TOKEN_NAME}' is forbidden (HTTP 403) — may be suspended or IP-blocked"
  echo "valid=false" >> "$GITHUB_OUTPUT"
  exit 1
elif [ "$HTTP_CODE" != "200" ]; then
  echo "::error::Token '${TOKEN_NAME}' auth check returned HTTP ${HTTP_CODE}"
  echo "valid=false" >> "$GITHUB_OUTPUT"
  exit 1
fi

# 2. Check scopes (from response headers)
SCOPES_HEADER=$(curl -s -I \
  -H "Authorization: Bearer ${GH_TOKEN}" \
  https://api.github.com/user | grep -i "x-oauth-scopes:" | cut -d: -f2- | tr -d ' \r')

if [ -n "$REQUIRED_SCOPES" ]; then
  IFS=',' read -ra REQUIRED <<< "$REQUIRED_SCOPES"
  for scope in "${REQUIRED[@]}"; do
    if ! echo "$SCOPES_HEADER" | grep -q "$scope"; then
      echo "::error::Token '${TOKEN_NAME}' missing required scope '${scope}' (has: ${SCOPES_HEADER})"
      echo "valid=false" >> "$GITHUB_OUTPUT"
      exit 1
    fi
  done
fi

# 3. Check rate limit
RATE_JSON=$(curl -s \
  -H "Authorization: Bearer ${GH_TOKEN}" \
  https://api.github.com/rate_limit)
REMAINING=$(echo "$RATE_JSON" | jq -r '.rate.remaining')
RESET=$(echo "$RATE_JSON" | jq -r '.rate.reset')

echo "rate_remaining=${REMAINING}" >> "$GITHUB_OUTPUT"

if [ "$REMAINING" -lt "$MIN_REMAINING" ]; then
  RESET_TIME=$(date -d "@${RESET}" -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -r "$RESET" -u +%Y-%m-%dT%H:%M:%SZ)
  echo "::warning::Token '${TOKEN_NAME}' rate limit low: ${REMAINING} remaining (resets at ${RESET_TIME})"
fi

# 4. Check token expiry (GitHub App installations have expiry)
EXPIRES=$(jq -r '.expires_at // empty' /tmp/auth-response.json 2>/dev/null || true)
if [ -n "$EXPIRES" ]; then
  echo "expires_at=${EXPIRES}" >> "$GITHUB_OUTPUT"
  echo "Token '${TOKEN_NAME}' expires at: ${EXPIRES}"
else
  echo "expires_at=none" >> "$GITHUB_OUTPUT"
fi

echo "valid=true" >> "$GITHUB_OUTPUT"
echo "Token '${TOKEN_NAME}' is healthy (rate: ${REMAINING} remaining)"
