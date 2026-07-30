#!/usr/bin/env bats
# Tests for sign-and-publish action validation steps.
#
# The two validation snippets are the only pure-shell, mockable logic in
# sign-and-publish/action.yml. Everything else (cosign, syft, oras, attest)
# requires live network/OIDC and is tested via integration CI.
#
# Covers:
#   Keyless validation step:
#     - ACTIONS_ID_TOKEN_REQUEST_URL set   → exit 0  (ok to proceed)
#     - ACTIONS_ID_TOKEN_REQUEST_URL unset → exit 1  (clear error message)
#     - ACTIONS_ID_TOKEN_REQUEST_URL empty → exit 1
#
#   Key-based validation step:
#     - COSIGN_PRIVATE_KEY set (non-empty) → exit 0
#     - COSIGN_PRIVATE_KEY empty           → exit 1
#     - COSIGN_PRIVATE_KEY unset           → exit 1 (set -u triggers or empty check)
#
#   Fix sigstore cache permissions step:
#     - target dir exists and is owned by the running user → chown succeeds, exit 0
#     - target dir missing → chown fails, `|| true` swallows it, exit 0 regardless
#
#   Attach SBOM via ORAS step (digest discovery):
#     - `oras discover` returns a matching SPDX referrer → digest extracted and emitted
#     - multiple referrers match → `head -n1` selects the first
#     - no matching referrer (empty digest) → `::error::` and exit 1 (no silent skip)

# ── Snippets verbatim from action.yml ────────────────────────────────────────

VALIDATE_KEYLESS='
set -euo pipefail
if [[ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ]]; then
  echo "::error::signing-mode=keyless requires '"'"'id-token: write'"'"' permission in the calling job."
  exit 1
fi
'

VALIDATE_KEY='
set -euo pipefail
if [[ -z "${COSIGN_PRIVATE_KEY}" ]]; then
  echo "::error::signing-mode=key requires inputs.signing-key to be set."
  exit 1
fi
'

# ── Keyless validation ────────────────────────────────────────────────────────

@test "keyless: ACTIONS_ID_TOKEN_REQUEST_URL set → passes" {
  export ACTIONS_ID_TOKEN_REQUEST_URL="https://token.actions.githubusercontent.com/...token"
  run bash -c "$VALIDATE_KEYLESS"
  [ "$status" -eq 0 ]
}

@test "keyless: ACTIONS_ID_TOKEN_REQUEST_URL unset → fails with error message" {
  unset ACTIONS_ID_TOKEN_REQUEST_URL
  run bash -c "$VALIDATE_KEYLESS"
  [ "$status" -ne 0 ]
  [[ "$output" == *"id-token: write"* ]]
}

@test "keyless: ACTIONS_ID_TOKEN_REQUEST_URL empty string → fails" {
  export ACTIONS_ID_TOKEN_REQUEST_URL=""
  run bash -c "$VALIDATE_KEYLESS"
  [ "$status" -ne 0 ]
}

@test "keyless: error output contains ::error:: annotation" {
  unset ACTIONS_ID_TOKEN_REQUEST_URL
  run bash -c "$VALIDATE_KEYLESS"
  [ "$status" -ne 0 ]
  [[ "$output" == *"::error::"* ]]
}

@test "keyless: error output mentions signing-mode=keyless" {
  unset ACTIONS_ID_TOKEN_REQUEST_URL
  run bash -c "$VALIDATE_KEYLESS"
  [ "$status" -ne 0 ]
  [[ "$output" == *"keyless"* ]]
}

# ── Key-based validation ──────────────────────────────────────────────────────

@test "key: COSIGN_PRIVATE_KEY set → passes" {
  export COSIGN_PRIVATE_KEY="-----BEGIN EC PRIVATE KEY-----\nfakekeydata\n-----END EC PRIVATE KEY-----"
  run bash -c "$VALIDATE_KEY"
  [ "$status" -eq 0 ]
}

@test "key: COSIGN_PRIVATE_KEY empty → fails with error message" {
  export COSIGN_PRIVATE_KEY=""
  run bash -c "$VALIDATE_KEY"
  [ "$status" -ne 0 ]
  [[ "$output" == *"signing-key"* ]]
}

@test "key: COSIGN_PRIVATE_KEY unset → fails (set -u or empty check)" {
  unset COSIGN_PRIVATE_KEY
  run bash -c "$VALIDATE_KEY"
  [ "$status" -ne 0 ]
}

@test "key: error output contains ::error:: annotation" {
  export COSIGN_PRIVATE_KEY=""
  run bash -c "$VALIDATE_KEY"
  [ "$status" -ne 0 ]
  [[ "$output" == *"::error::"* ]]
}

@test "key: error output mentions signing-mode=key" {
  export COSIGN_PRIVATE_KEY=""
  run bash -c "$VALIDATE_KEY"
  [ "$status" -ne 0 ]
  [[ "$output" == *"signing-mode=key"* ]]
}

# ── Interaction: both snippets independent ────────────────────────────────────

@test "keyless snippet is unaffected by COSIGN_PRIVATE_KEY being set" {
  unset ACTIONS_ID_TOKEN_REQUEST_URL
  export COSIGN_PRIVATE_KEY="some-key"
  run bash -c "$VALIDATE_KEYLESS"
  # keyless check doesn't care about COSIGN_PRIVATE_KEY
  [ "$status" -ne 0 ]
  [[ "$output" == *"id-token"* ]]
}

@test "key snippet is unaffected by ACTIONS_ID_TOKEN_REQUEST_URL being set" {
  export COSIGN_PRIVATE_KEY=""
  export ACTIONS_ID_TOKEN_REQUEST_URL="https://token.actions.githubusercontent.com/token"
  run bash -c "$VALIDATE_KEY"
  # key check doesn't care about OIDC URL
  [ "$status" -ne 0 ]
  [[ "$output" == *"signing-key"* ]]
}

# ── Fix sigstore cache permissions ────────────────────────────────────────────
# Verbatim from action.yml step "Fix sigstore cache permissions". Uses a `sudo`
# pass-through mock (per docs/skills/testing.md) so it runs unprivileged.

SIGSTORE_CACHE_FIX_SNIPPET='
sudo chown -R "$(id -u):$(id -g)" "${HOME}/.sigstore" 2>/dev/null || true
'

setup_sudo_passthrough() {
  export MOCK_DIR="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$MOCK_DIR"
  cat > "${MOCK_DIR}/sudo" <<'EOF'
#!/usr/bin/env bash
exec "$@"
EOF
  chmod +x "${MOCK_DIR}/sudo"
  export PATH="${MOCK_DIR}:${PATH}"
}

@test "sigstore cache fix: existing, owned .sigstore dir → chown succeeds, exit 0" {
  setup_sudo_passthrough
  HOME="${BATS_TEST_TMPDIR}/home_with_cache"
  mkdir -p "${HOME}/.sigstore"
  run env HOME="$HOME" PATH="$PATH" bash -c "$SIGSTORE_CACHE_FIX_SNIPPET"
  [ "$status" -eq 0 ]
}

@test "sigstore cache fix: missing .sigstore dir → chown fails but '|| true' swallows it, still exit 0" {
  setup_sudo_passthrough
  HOME="${BATS_TEST_TMPDIR}/home_without_cache"
  # deliberately do not create ${HOME}/.sigstore
  run env HOME="$HOME" PATH="$PATH" bash -c "$SIGSTORE_CACHE_FIX_SNIPPET"
  [ "$status" -eq 0 ]
  # stderr is redirected to /dev/null by the snippet itself; nothing should
  # leak into the captured output either.
  [ -z "$output" ]
}

# ── Attach SBOM via ORAS: digest discovery ────────────────────────────────────
# Verbatim (mocked-binary) form of the "Attach SBOM via ORAS" step's digest
# discovery logic from action.yml. `oras attach` is mocked as a no-op; `oras
# discover` is mocked per-test to return canned JSON so the jq filter, `head
# -n1` selection, and empty-digest error propagation are exercised directly.

ORAS_DISCOVER_SNIPPET='
set -euo pipefail
oras attach \
  --artifact-type application/vnd.spdx+json \
  --annotation "filename=$(basename "${SBOM_PATH}")" \
  "${IMAGE}@${DIGEST}" \
  "$(basename "${SBOM_PATH}")"
SBOM_DIGEST=$(oras discover --format json "${IMAGE}@${DIGEST}" \
  | jq -r '"'"'.referrers[] | select(.artifactType == "application/vnd.spdx+json") | .digest'"'"' \
  | head -n1)
if [[ -z "${SBOM_DIGEST}" ]]; then
  echo "::error::Failed to discover attached SBOM digest"
  exit 1
fi
echo "sbom-digest=${SBOM_DIGEST}" >> "$GITHUB_OUTPUT"
'

setup_oras_mocks() {
  local discover_json="$1"
  export MOCK_DIR="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$MOCK_DIR"
  cat > "${MOCK_DIR}/oras" <<EOF
#!/usr/bin/env bash
case "\$1" in
  attach)
    exit 0
    ;;
  discover)
    cat <<'JSON'
${discover_json}
JSON
    ;;
  *)
    echo "unexpected oras subcommand: \$1" >&2
    exit 1
    ;;
esac
EOF
  chmod +x "${MOCK_DIR}/oras"
  export PATH="${MOCK_DIR}:${PATH}"
}

setup() {
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export DIGEST="sha256:abc123"
  export SBOM_PATH="sbom_out/bluefin/sbom.json"
  export GITHUB_OUTPUT="${BATS_TEST_TMPDIR}/github_output"
  touch "$GITHUB_OUTPUT"
}

@test "oras discover: single matching SPDX referrer → digest extracted and emitted" {
  setup_oras_mocks '{"referrers":[{"artifactType":"application/vnd.spdx+json","digest":"sha256:sbomdigest111"}]}'
  run bash -c "$ORAS_DISCOVER_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q "sbom-digest=sha256:sbomdigest111" "$GITHUB_OUTPUT"
}

@test "oras discover: multiple matching referrers → head -n1 selects the first" {
  setup_oras_mocks '{"referrers":[{"artifactType":"application/vnd.spdx+json","digest":"sha256:first111"},{"artifactType":"application/vnd.spdx+json","digest":"sha256:second222"}]}'
  run bash -c "$ORAS_DISCOVER_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q "sbom-digest=sha256:first111" "$GITHUB_OUTPUT"
  ! grep -q "second222" "$GITHUB_OUTPUT"
}

@test "oras discover: non-SPDX referrers are filtered out by artifactType" {
  setup_oras_mocks '{"referrers":[{"artifactType":"application/vnd.oci.image.manifest.v1+json","digest":"sha256:notasbom"},{"artifactType":"application/vnd.spdx+json","digest":"sha256:realsbom999"}]}'
  run bash -c "$ORAS_DISCOVER_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q "sbom-digest=sha256:realsbom999" "$GITHUB_OUTPUT"
}

@test "oras discover: no matching referrer → empty digest → ::error:: and exit 1 (no silent skip)" {
  setup_oras_mocks '{"referrers":[]}'
  run bash -c "$ORAS_DISCOVER_SNIPPET"
  [ "$status" -ne 0 ]
  [[ "$output" == *"::error::"* ]]
  [[ "$output" == *"Failed to discover attached SBOM digest"* ]]
  # error path must not have written a (bogus empty) sbom-digest output
  ! grep -q "^sbom-digest=" "$GITHUB_OUTPUT"
}

@test "oras discover: only non-SPDX referrers present → empty digest → exit 1" {
  setup_oras_mocks '{"referrers":[{"artifactType":"application/vnd.oci.image.manifest.v1+json","digest":"sha256:notasbom"}]}'
  run bash -c "$ORAS_DISCOVER_SNIPPET"
  [ "$status" -ne 0 ]
  [[ "$output" == *"::error::"* ]]
}
