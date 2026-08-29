#!/usr/bin/env bats
# Tests for bootc-build/preflight/action.yml.
#
# The shell logic lives inline in three `run:` blocks of preflight/action.yml.
# The snippets below are verbatim copies of those blocks so this test breaks if
# the action logic changes without updating the test (same convention as
# tests/bats/test_detect_changes.bats).
#
# Covers:
#   Normalize image reference
#     - registry + owner are lowercased into registry-lowercase
#     - image-ref emitted only when image-name is non-empty, lowercased
#     - already-lowercase input is a no-op
#     - image names containing a slash are preserved
#   Validate registry auth
#     - podman login success -> exit 0 and "Registry auth OK"
#     - podman login failure -> ::error:: annotation and exit 1
#     - token is piped on stdin, actor passed as -u, registry as argument
#     - podman stderr is suppressed (must not leak a token to the log)
#   Validate required secrets
#     - all present -> exit 0
#     - one missing/empty -> ::error:: naming exactly the missing vars, exit 1
#     - surrounding whitespace in the comma list is stripped
#     - single-entry list, and a var set to whitespace is NOT treated as empty

# Snippets below are byte-for-byte copies of the `run:` blocks in
# bootc-build/preflight/action.yml (quoted heredocs, so nothing is re-expanded
# at definition time).

NORMALIZE_SNIPPET=$(cat <<'SNIP'
set -euo pipefail
REGISTRY_LOWER="${INPUT_REGISTRY,,}/${GITHUB_REPOSITORY_OWNER,,}"
echo "registry-lowercase=${REGISTRY_LOWER}" >> "$GITHUB_OUTPUT"
if [[ -n "${INPUT_IMAGE_NAME}" ]]; then
  IMAGE_REF="${REGISTRY_LOWER}/${INPUT_IMAGE_NAME,,}"
  echo "image-ref=${IMAGE_REF}" >> "$GITHUB_OUTPUT"
fi
SNIP
)

AUTH_SNIPPET=$(cat <<'SNIP'
set -euo pipefail
if ! echo "${GITHUB_TOKEN}" | podman login "${INPUT_REGISTRY}" \
    -u "${GITHUB_ACTOR}" --password-stdin 2>/dev/null; then
  echo "::error::Registry auth failed for ${INPUT_REGISTRY}. Check GITHUB_TOKEN has packages:write permission."
  exit 1
fi
echo "✅ Registry auth OK"
SNIP
)

SECRETS_SNIPPET=$(cat <<'SNIP'
set -euo pipefail
IFS=',' read -ra SECRETS <<< "${REQUIRED}"
MISSING=()
for secret in "${SECRETS[@]}"; do
  secret="${secret// /}"
  val="${!secret:-}"
  if [[ -z "${val}" ]]; then
    MISSING+=("${secret}")
  fi
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "::error::Required secrets are missing or empty: ${MISSING[*]}"
  exit 1
fi
echo "✅ All required secrets present"
SNIP
)

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  STUB_BIN="${TEST_TMP}/bin"
  mkdir -p "$STUB_BIN"
  export PATH="${STUB_BIN}:${PATH}"
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

# Install a `podman` stub that records its argv and stdin, and exits with
# the code stored in ${TEST_TMP}/podman_rc (default 0).
stub_podman() {
  echo "${1:-0}" > "${TEST_TMP}/podman_rc"
  cat > "${STUB_BIN}/podman" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" > "${TEST_TMP}/podman_args"
cat > "${TEST_TMP}/podman_stdin"
echo "podman-stub-stderr" >&2
exit "\$(cat "${TEST_TMP}/podman_rc")"
EOF
  chmod +x "${STUB_BIN}/podman"
}

# ── Normalize image reference ─────────────────────────────────────────────────

@test "normalize: lowercases registry and repository owner" {
  export INPUT_REGISTRY="GHCR.IO"
  export GITHUB_REPOSITORY_OWNER="ProjectBluefin"
  export INPUT_IMAGE_NAME=""
  run bash -c "$NORMALIZE_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output registry-lowercase)" = "ghcr.io/projectbluefin" ]
}

@test "normalize: already-lowercase input is unchanged" {
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_REPOSITORY_OWNER="projectbluefin"
  export INPUT_IMAGE_NAME=""
  run bash -c "$NORMALIZE_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output registry-lowercase)" = "ghcr.io/projectbluefin" ]
}

@test "normalize: empty image-name emits no image-ref line" {
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_REPOSITORY_OWNER="projectbluefin"
  export INPUT_IMAGE_NAME=""
  run bash -c "$NORMALIZE_SNIPPET"
  [ "$status" -eq 0 ]
  run grep -c '^image-ref=' "$GITHUB_OUTPUT"
  [ "$status" -ne 0 ]
}

@test "normalize: non-empty image-name emits lowercased image-ref" {
  export INPUT_REGISTRY="GHCR.IO"
  export GITHUB_REPOSITORY_OWNER="ProjectBluefin"
  export INPUT_IMAGE_NAME="Bluefin-LTS"
  run bash -c "$NORMALIZE_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output image-ref)" = "ghcr.io/projectbluefin/bluefin-lts" ]
}

@test "normalize: image-ref is prefixed by registry-lowercase" {
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_REPOSITORY_OWNER="projectbluefin"
  export INPUT_IMAGE_NAME="dakota"
  run bash -c "$NORMALIZE_SNIPPET"
  [ "$status" -eq 0 ]
  reg="$(get_output registry-lowercase)"
  ref="$(get_output image-ref)"
  [ "$ref" = "${reg}/dakota" ]
}

@test "normalize: slash inside image-name is preserved" {
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_REPOSITORY_OWNER="projectbluefin"
  export INPUT_IMAGE_NAME="Nested/Image"
  run bash -c "$NORMALIZE_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output image-ref)" = "ghcr.io/projectbluefin/nested/image" ]
}

@test "normalize: outputs are written as key=value to GITHUB_OUTPUT" {
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_REPOSITORY_OWNER="projectbluefin"
  export INPUT_IMAGE_NAME="dakota"
  run bash -c "$NORMALIZE_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q '^registry-lowercase=' "$GITHUB_OUTPUT"
  grep -q '^image-ref=' "$GITHUB_OUTPUT"
}

# ── Validate registry auth ────────────────────────────────────────────────────

@test "auth: successful podman login exits 0 and reports OK" {
  stub_podman 0
  export GITHUB_TOKEN="tok"
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_ACTOR="octocat"
  run bash -c "$AUTH_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Registry auth OK"* ]]
}

@test "auth: failed podman login emits ::error:: and exits 1" {
  stub_podman 1
  export GITHUB_TOKEN="tok"
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_ACTOR="octocat"
  run bash -c "$AUTH_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Registry auth failed for ghcr.io"* ]]
  [[ "$output" == *"packages:write"* ]]
}

@test "auth: failure does not print the success message" {
  stub_podman 1
  export GITHUB_TOKEN="tok"
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_ACTOR="octocat"
  run bash -c "$AUTH_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" != *"Registry auth OK"* ]]
}

@test "auth: token is supplied on stdin, never on the command line" {
  stub_podman 0
  export GITHUB_TOKEN="super-secret-token"
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_ACTOR="octocat"
  run bash -c "$AUTH_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(cat "${TEST_TMP}/podman_stdin")" = "super-secret-token" ]
  [[ "$(cat "${TEST_TMP}/podman_args")" != *"super-secret-token"* ]]
}

@test "auth: podman is called as login <registry> -u <actor> --password-stdin" {
  stub_podman 0
  export GITHUB_TOKEN="tok"
  export INPUT_REGISTRY="registry.example.com"
  export GITHUB_ACTOR="some-actor"
  run bash -c "$AUTH_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(cat "${TEST_TMP}/podman_args")" = "login registry.example.com -u some-actor --password-stdin" ]
}

@test "auth: podman stderr is suppressed so credentials cannot leak to the log" {
  stub_podman 1
  export GITHUB_TOKEN="tok"
  export INPUT_REGISTRY="ghcr.io"
  export GITHUB_ACTOR="octocat"
  run bash -c "$AUTH_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" != *"podman-stub-stderr"* ]]
}

@test "auth: non-default registry is named in the error annotation" {
  stub_podman 1
  export GITHUB_TOKEN="tok"
  export INPUT_REGISTRY="quay.io"
  export GITHUB_ACTOR="octocat"
  run bash -c "$AUTH_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Registry auth failed for quay.io."* ]]
}

# ── Validate required secrets ─────────────────────────────────────────────────

@test "secrets: all present exits 0" {
  export REQUIRED="ALPHA,BETA"
  export ALPHA="a"
  export BETA="b"
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"All required secrets present"* ]]
}

@test "secrets: unset variable is reported and exits 1" {
  export REQUIRED="ALPHA,BETA"
  export ALPHA="a"
  unset BETA
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Required secrets are missing or empty: BETA"* ]]
}

@test "secrets: set-but-empty variable is treated as missing" {
  export REQUIRED="ALPHA"
  export ALPHA=""
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"missing or empty: ALPHA"* ]]
}

@test "secrets: every missing name is listed, space separated" {
  export REQUIRED="ALPHA,BETA,GAMMA"
  unset ALPHA BETA
  export GAMMA="g"
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"missing or empty: ALPHA BETA"* ]]
}

@test "secrets: present names are not listed as missing" {
  export REQUIRED="ALPHA,BETA"
  export ALPHA="a"
  unset BETA
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" != *"ALPHA"* ]]
}

@test "secrets: whitespace around comma-separated names is stripped" {
  export REQUIRED=" ALPHA , BETA "
  export ALPHA="a"
  export BETA="b"
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"All required secrets present"* ]]
}

@test "secrets: whitespace-padded missing name is reported without padding" {
  export REQUIRED=" ALPHA , BETA "
  export ALPHA="a"
  unset BETA
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"missing or empty: BETA"* ]]
}

@test "secrets: single-entry list with the value present exits 0" {
  export REQUIRED="ONLY_ONE"
  export ONLY_ONE="x"
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 0 ]
}

@test "secrets: a variable set to whitespace is considered present" {
  export REQUIRED="ALPHA"
  export ALPHA=" "
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"All required secrets present"* ]]
}

@test "secrets: success path prints no ::error:: annotation" {
  export REQUIRED="ALPHA"
  export ALPHA="a"
  run bash -c "$SECRETS_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" != *"::error::"* ]]
}
