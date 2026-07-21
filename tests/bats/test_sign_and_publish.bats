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

# ── SBOM path generation ─────────────────────────────────────────────────────
# These tests cover the Generate SBOM step shell logic inline.

SBOM_PATH_SNIPPET='
set -euo pipefail
NAME="${IMAGE_NAME:-$(basename "${IMAGE}")}"
SBOM_DIR="sbom_out/${NAME}"
mkdir -p "${SBOM_DIR}"
# stub syft: write placeholder SBOM file
touch "${SBOM_DIR}/sbom.json"
echo "sbom-path=${SBOM_DIR}/sbom.json" >> "$GITHUB_OUTPUT"
echo "sbom-dir=${SBOM_DIR}" >> "$GITHUB_OUTPUT"
echo "image-name=${NAME}" >> "$GITHUB_OUTPUT"
'

setup() {
  export TMPDIR
  TMPDIR=$(mktemp -d)
  export GITHUB_OUTPUT="${TMPDIR}/github_output"
  touch "$GITHUB_OUTPUT"
  export DIGEST="sha256:abc123"
}

teardown() {
  rm -rf "$TMPDIR"
}

@test "sbom-path: IMAGE_NAME set → NAME uses it directly" {
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export IMAGE_NAME="bluefin"
  run bash -c "cd '$TMPDIR' && $SBOM_PATH_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q "image-name=bluefin" "$GITHUB_OUTPUT"
}

@test "sbom-path: IMAGE_NAME unset → NAME falls back to basename of IMAGE" {
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  unset IMAGE_NAME
  run bash -c "cd '$TMPDIR' && $SBOM_PATH_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q "image-name=bluefin" "$GITHUB_OUTPUT"
}

@test "sbom-path: full registry URL → basename strips registry prefix" {
  export IMAGE="ghcr.io/projectbluefin/aurora-dx"
  unset IMAGE_NAME
  run bash -c "cd '$TMPDIR' && $SBOM_PATH_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q "image-name=aurora-dx" "$GITHUB_OUTPUT"
}

@test "sbom-path: GITHUB_OUTPUT receives correct sbom-path entry" {
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export IMAGE_NAME="bluefin"
  run bash -c "cd '$TMPDIR' && $SBOM_PATH_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q "sbom-path=sbom_out/bluefin/sbom.json" "$GITHUB_OUTPUT"
}

@test "sbom-path: GITHUB_OUTPUT receives correct sbom-dir entry" {
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export IMAGE_NAME="bluefin"
  run bash -c "cd '$TMPDIR' && $SBOM_PATH_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q "sbom-dir=sbom_out/bluefin" "$GITHUB_OUTPUT"
}

@test "sbom-path: sbom_out directory is created under TMPDIR" {
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export IMAGE_NAME="bluefin"
  run bash -c "cd '$TMPDIR' && $SBOM_PATH_SNIPPET"
  [ "$status" -eq 0 ]
  [ -d "$TMPDIR/sbom_out/bluefin" ]
}

@test "sbom-path: IMAGE_NAME empty string → falls back to basename" {
  export IMAGE="ghcr.io/projectbluefin/bluefin-nvidia"
  export IMAGE_NAME=""
  run bash -c "cd '$TMPDIR' && $SBOM_PATH_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q "image-name=bluefin-nvidia" "$GITHUB_OUTPUT"
}
