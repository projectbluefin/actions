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

FIX_SIGSTORE_CACHE='
sudo chown -R "$(id -u):$(id -g)" "${HOME}/.sigstore" 2>/dev/null || true
'

ATTACH_SBOM='
set -euo pipefail
cd "$(dirname "${SBOM_PATH}")"
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

GENERATE_SBOM='
set -euo pipefail
NAME="${IMAGE_NAME:-$(basename "${IMAGE}")}"
SBOM_DIR="sbom_out/${NAME}"
mkdir -p "${SBOM_DIR}"
"${SYFT_CMD}" "${IMAGE}@${DIGEST}" -o spdx-json="${SBOM_DIR}/sbom.json"
echo "sbom-path=${SBOM_DIR}/sbom.json" >> "$GITHUB_OUTPUT"
echo "sbom-dir=${SBOM_DIR}" >> "$GITHUB_OUTPUT"
echo "image-name=${NAME}" >> "$GITHUB_OUTPUT"
'

setup() {
  TEST_TMP=$(mktemp -d)
  export TEST_TMP
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"
  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

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

# ── Sigstore cache fix ────────────────────────────────────────────────────────

@test "sigstore cache fix: runs chown with uid:gid and does not fail" {
  export HOME="${TEST_TMP}/home"
  mkdir -p "${HOME}/.sigstore"
  export SUDO_CALL_LOG="${TEST_TMP}/sudo_calls.log"
  touch "${SUDO_CALL_LOG}"

  cat > "${MOCK_DIR}/sudo" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "${SUDO_CALL_LOG}"
"\$@"
EOF
  chmod +x "${MOCK_DIR}/sudo"

  run bash -c "$FIX_SIGSTORE_CACHE"
  [ "$status" -eq 0 ]
  grep -q "^chown -R [0-9][0-9]*:[0-9][0-9]* ${HOME}/.sigstore$" "${SUDO_CALL_LOG}"
}

@test "sigstore cache fix: tolerates chown failure (best-effort step)" {
  export HOME="${TEST_TMP}/home"
  mkdir -p "${HOME}/.sigstore"

  cat > "${MOCK_DIR}/sudo" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
  chmod +x "${MOCK_DIR}/sudo"

  run bash -c "$FIX_SIGSTORE_CACHE"
  [ "$status" -eq 0 ]
}

# ── Attach SBOM via ORAS ───────────────────────────────────────────────────────

@test "attach sbom: discovers SPDX referrer digest and writes output" {
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export DIGEST="sha256:feedface"
  export SBOM_PATH="${TEST_TMP}/sbom_out/bluefin/sbom.json"
  mkdir -p "$(dirname "${SBOM_PATH}")"
  echo '{}' > "${SBOM_PATH}"

  cat > "${MOCK_DIR}/oras" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "attach" ]]; then
  exit 0
fi
if [[ "$1" == "discover" ]]; then
  cat <<'JSON'
{"referrers":[{"artifactType":"application/vnd.spdx+json","digest":"sha256:spdx123"},{"artifactType":"application/vnd.in-toto+json","digest":"sha256:other"}]}
JSON
  exit 0
fi
exit 1
EOF
  chmod +x "${MOCK_DIR}/oras"

  run bash -c "$ATTACH_SBOM"
  [ "$status" -eq 0 ]
  [ "$(get_output sbom-digest)" = "sha256:spdx123" ]
}

@test "attach sbom: fails with explicit error when discover finds no SPDX digest" {
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export DIGEST="sha256:feedface"
  export SBOM_PATH="${TEST_TMP}/sbom_out/bluefin/sbom.json"
  mkdir -p "$(dirname "${SBOM_PATH}")"
  echo '{}' > "${SBOM_PATH}"

  cat > "${MOCK_DIR}/oras" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "attach" ]]; then
  exit 0
fi
if [[ "$1" == "discover" ]]; then
  echo '{"referrers":[{"artifactType":"application/vnd.in-toto+json","digest":"sha256:other"}]}'
  exit 0
fi
exit 1
EOF
  chmod +x "${MOCK_DIR}/oras"

  run bash -c "$ATTACH_SBOM"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Failed to discover attached SBOM digest"* ]]
}

# ── SBOM path generation ──────────────────────────────────────────────────────

make_syft() {
  export SYFT_CMD="${TEST_TMP}/syft"
  cat > "${SYFT_CMD}" <<'EOF'
#!/usr/bin/env bash
out="${*: -1}"
outfile="${out#spdx-json=}"
mkdir -p "$(dirname "$outfile")"
echo "{}" > "$outfile"
EOF
  chmod +x "${SYFT_CMD}"
}

@test "sbom: explicit IMAGE_NAME sets output path under sbom_out/<name>" {
  cd "${TEST_TMP}"
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export DIGEST="sha256:deadbeef"
  export IMAGE_NAME="custom-image"
  make_syft

  run bash -c "$GENERATE_SBOM"
  [ "$status" -eq 0 ]
  [ "$(get_output sbom-path)" = "sbom_out/custom-image/sbom.json" ]
  [ "$(get_output sbom-dir)" = "sbom_out/custom-image" ]
  [ "$(get_output image-name)" = "custom-image" ]
}

@test "sbom: empty IMAGE_NAME falls back to basename(IMAGE)" {
  cd "${TEST_TMP}"
  export IMAGE="ghcr.io/projectbluefin/bluefin-lts"
  export DIGEST="sha256:beadfeed"
  export IMAGE_NAME=""
  make_syft

  run bash -c "$GENERATE_SBOM"
  [ "$status" -eq 0 ]
  [ "$(get_output sbom-path)" = "sbom_out/bluefin-lts/sbom.json" ]
  [ "$(get_output sbom-dir)" = "sbom_out/bluefin-lts" ]
  [ "$(get_output image-name)" = "bluefin-lts" ]
}

@test "attach sbom: propagates oras attach failure" {
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export DIGEST="sha256:feedface"
  export SBOM_PATH="${TEST_TMP}/sbom_out/bluefin/sbom.json"
  mkdir -p "$(dirname "${SBOM_PATH}")"
  echo '{}' > "${SBOM_PATH}"

  cat > "${MOCK_DIR}/oras" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "attach" ]]; then
  echo "attach failed" >&2
  exit 7
fi
exit 0
EOF
  chmod +x "${MOCK_DIR}/oras"

  run bash -c "$ATTACH_SBOM"
  [ "$status" -ne 0 ]
}
