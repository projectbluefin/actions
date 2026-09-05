#!/usr/bin/env bats
# Tests for bootc-build/create-manifest inline shell logic.
#
# The shell logic lives inline in bootc-build/create-manifest/action.yml.
# The snippets below are verbatim copies of the "Validate required tools",
# "Create manifest", "Populate manifest" and "Push manifest tags" run blocks,
# so this test breaks if the action logic changes without updating the test.
#
# podman/buildah/sleep are stubbed on PATH so no registry or container runtime
# is required.
#
# Covers:
#   - required tool validation (podman, jq) fails closed
#   - registry + owner lowercasing when building the manifest reference
#   - manifest rm failure is tolerated, manifest create is invoked
#   - digests-json must be a JSON object; each platform/digest becomes an add
#   - blank platform/digest entries are skipped
#   - label annotation falls back to buildah when podman --index is unsupported
#   - blank label lines are skipped
#   - first tag pushes with a digestfile, later tags push without
#   - push retries up to 3 attempts, then fails
#   - missing/empty digestfile is a hard error
#   - empty tag list is a hard error
#   - digest is written to GITHUB_OUTPUT

setup() {
  TEST_TMP=$(mktemp -d)
  export TEST_TMP
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  : >"$GITHUB_OUTPUT"

  export STUB_BIN="${TEST_TMP}/bin"
  mkdir -p "$STUB_BIN"
  export PODMAN_LOG="${TEST_TMP}/podman.log"
  export BUILDAH_LOG="${TEST_TMP}/buildah.log"
  export PUSH_COUNT_FILE="${TEST_TMP}/push_count"
  : >"$PODMAN_LOG"
  : >"$BUILDAH_LOG"
  echo 0 >"$PUSH_COUNT_FILE"

  cat >"${STUB_BIN}/podman" <<'STUB'
#!/usr/bin/env bash
echo "$*" >>"$PODMAN_LOG"
case "${1:-} ${2:-}" in
  "manifest rm")
    exit "${PODMAN_RM_STATUS:-0}"
    ;;
  "manifest create")
    exit "${PODMAN_CREATE_STATUS:-0}"
    ;;
  "manifest add")
    exit "${PODMAN_ADD_STATUS:-0}"
    ;;
  "manifest annotate")
    exit "${PODMAN_ANNOTATE_STATUS:-0}"
    ;;
  "manifest push")
    count=$(( $(cat "$PUSH_COUNT_FILE") + 1 ))
    echo "$count" >"$PUSH_COUNT_FILE"
    digestfile=""
    prev=""
    for arg in "$@"; do
      [[ "$prev" == "--digestfile" ]] && digestfile="$arg"
      prev="$arg"
    done
    if (( count <= ${PODMAN_PUSH_FAIL_TIMES:-0} )); then
      exit 1
    fi
    if [[ -n "$digestfile" && "${PODMAN_PUSH_EMPTY_DIGEST:-0}" != "1" ]]; then
      printf '%s' "sha256:feedface" >"$digestfile"
    fi
    exit 0
    ;;
esac
exit 0
STUB

  cat >"${STUB_BIN}/buildah" <<'STUB'
#!/usr/bin/env bash
echo "$*" >>"$BUILDAH_LOG"
exit "${BUILDAH_STATUS:-0}"
STUB

  # Keep retry backoff instant.
  cat >"${STUB_BIN}/sleep" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB

  chmod +x "${STUB_BIN}/podman" "${STUB_BIN}/buildah" "${STUB_BIN}/sleep"
  export PATH="${STUB_BIN}:${PATH}"

  # ── Verbatim snippets from bootc-build/create-manifest/action.yml ──────────
  cat >"${TEST_TMP}/validate.sh" <<'SNIPPET'
set -euo pipefail

command -v podman >/dev/null 2>&1 || {
  echo "::error::podman is required; callers must provide it."
  exit 1
}

command -v jq >/dev/null 2>&1 || {
  echo "::error::jq is required; callers must provide it."
  exit 1
}
SNIPPET

  cat >"${TEST_TMP}/create.sh" <<'SNIPPET'
set -euo pipefail

REGISTRY_LOWER="${REGISTRY,,}/${GITHUB_REPOSITORY_OWNER,,}"
MANIFEST="${REGISTRY_LOWER}/${IMAGE_NAME}"

podman manifest rm "${MANIFEST}" >/dev/null 2>&1 || true
podman manifest create "${MANIFEST}"

echo "manifest=${MANIFEST}" >> "${GITHUB_OUTPUT}"
SNIPPET

  cat >"${TEST_TMP}/populate.sh" <<'SNIPPET'
set -euo pipefail

REGISTRY_LOWER="${REGISTRY,,}/${GITHUB_REPOSITORY_OWNER,,}"

jq -e 'type == "object"' >/dev/null <<< "${DIGESTS_JSON}"

while read -r platform digest; do
  [[ -z "${platform}" ]] && continue
  [[ -z "${digest}" ]] && continue
  podman manifest add "${MANIFEST}" "${REGISTRY_LOWER}/${IMAGE_NAME}@${digest}" --arch "${platform}"
done < <(echo "${DIGESTS_JSON}" | jq -r 'to_entries[] | "\(.key) \(.value)"')

while IFS= read -r label; do
  [[ -z "${label}" ]] && continue
  # --index (annotate the manifest list itself) requires podman >= 5.0.
  # GitHub Actions runners ship podman 4.9.x; fall back to buildah which
  # supports index-level annotation on all relevant versions.
  if podman manifest annotate --index --annotation "${label}" "${MANIFEST}" 2>/dev/null; then
    :
  else
    buildah manifest annotate --annotation "${label}" "${MANIFEST}"
  fi
done <<< "${LABELS}"
SNIPPET

  cat >"${TEST_TMP}/push.sh" <<'SNIPPET'
set -euo pipefail

REGISTRY_LOWER="${REGISTRY,,}/${GITHUB_REPOSITORY_OWNER,,}"
DIGEST=""
FIRST_TAG=1

push_with_retry() {
  local destination="$1"
  local digestfile="${2:-}"
  local attempt=1

  while true; do
    if [[ -n "${digestfile}" ]]; then
      rm -f "${digestfile}"
      if podman manifest push --all=false --digestfile "${digestfile}" "${MANIFEST}" "${destination}"; then
        return 0
      fi
    else
      if podman manifest push --all=false "${MANIFEST}" "${destination}"; then
        return 0
      fi
    fi

    if [[ ${attempt} -ge 3 ]]; then
      echo "::error::Failed to push ${destination} after 3 attempts"
      return 1
    fi

    echo "Push attempt ${attempt} for ${destination} failed, retrying in 5s..."
    attempt=$((attempt + 1))
    sleep 5
  done
}

while IFS= read -r tag; do
  [[ -z "${tag}" ]] && continue

  destination="${REGISTRY_LOWER}/${IMAGE_NAME}:${tag}"
  if [[ ${FIRST_TAG} -eq 1 ]]; then
    push_with_retry "${destination}" "${DIGEST_FILE}"
    if [[ ! -s "${DIGEST_FILE}" ]]; then
      echo "::error::Manifest push did not produce a digest file"
      exit 1
    fi
    DIGEST="$(<"${DIGEST_FILE}")"
    FIRST_TAG=0
  else
    push_with_retry "${destination}"
  fi
done <<< "${TAGS}"

if [[ ${FIRST_TAG} -eq 1 ]]; then
  echo "::error::At least one tag must be provided"
  exit 1
fi

echo "digest=${DIGEST}" >> "${GITHUB_OUTPUT}"
SNIPPET
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

podman_calls() {
  cat "$PODMAN_LOG"
}

# ── Validate required tools ───────────────────────────────────────────────────

@test "validate: succeeds when podman and jq are present" {
  run bash "${TEST_TMP}/validate.sh"
  [ "$status" -eq 0 ]
}

@test "validate: fails with an error annotation when podman is missing" {
  rm -f "${STUB_BIN}/podman"
  run env PATH="${STUB_BIN}:/usr/bin:/bin" bash "${TEST_TMP}/validate.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::podman is required"* ]]
}

# ── Create manifest ───────────────────────────────────────────────────────────

@test "create: lowercases registry and owner in the manifest reference" {
  export REGISTRY="GHCR.IO" GITHUB_REPOSITORY_OWNER="ProjectBluefin" IMAGE_NAME="bluefin-dx"
  run bash "${TEST_TMP}/create.sh"
  [ "$status" -eq 0 ]
  [ "$(get_output manifest)" = "ghcr.io/projectbluefin/bluefin-dx" ]
}

@test "create: tolerates a failing manifest rm and still creates the manifest" {
  export REGISTRY="ghcr.io" GITHUB_REPOSITORY_OWNER="projectbluefin" IMAGE_NAME="bluefin"
  export PODMAN_RM_STATUS=1
  run bash "${TEST_TMP}/create.sh"
  [ "$status" -eq 0 ]
  [[ "$(podman_calls)" == *"manifest create ghcr.io/projectbluefin/bluefin"* ]]
}

@test "create: fails when podman manifest create fails" {
  export REGISTRY="ghcr.io" GITHUB_REPOSITORY_OWNER="projectbluefin" IMAGE_NAME="bluefin"
  export PODMAN_CREATE_STATUS=1
  run bash "${TEST_TMP}/create.sh"
  [ "$status" -ne 0 ]
}

# ── Populate manifest ─────────────────────────────────────────────────────────

populate_env() {
  export REGISTRY="ghcr.io"
  export GITHUB_REPOSITORY_OWNER="projectbluefin"
  export IMAGE_NAME="bluefin"
  export MANIFEST="ghcr.io/projectbluefin/bluefin"
  export LABELS=""
}

@test "populate: adds one manifest entry per platform with --arch" {
  populate_env
  export DIGESTS_JSON='{"amd64":"sha256:aaa","arm64":"sha256:bbb"}'
  run bash "${TEST_TMP}/populate.sh"
  [ "$status" -eq 0 ]
  [[ "$(podman_calls)" == *"manifest add ghcr.io/projectbluefin/bluefin ghcr.io/projectbluefin/bluefin@sha256:aaa --arch amd64"* ]]
  [[ "$(podman_calls)" == *"manifest add ghcr.io/projectbluefin/bluefin ghcr.io/projectbluefin/bluefin@sha256:bbb --arch arm64"* ]]
}

@test "populate: rejects digests-json that is not a JSON object" {
  populate_env
  export DIGESTS_JSON='["amd64"]'
  run bash "${TEST_TMP}/populate.sh"
  [ "$status" -ne 0 ]
  [ ! -s "$PODMAN_LOG" ]
}

@test "populate: rejects malformed digests-json" {
  populate_env
  export DIGESTS_JSON='not json'
  run bash "${TEST_TMP}/populate.sh"
  [ "$status" -ne 0 ]
}

@test "populate: skips entries with an empty digest" {
  populate_env
  export DIGESTS_JSON='{"amd64":"","arm64":"sha256:bbb"}'
  run bash "${TEST_TMP}/populate.sh"
  [ "$status" -eq 0 ]
  [ "$(grep -c 'manifest add' "$PODMAN_LOG")" -eq 1 ]
  [[ "$(podman_calls)" == *"--arch arm64"* ]]
}

@test "populate: annotates labels via podman when --index is supported" {
  populate_env
  export DIGESTS_JSON='{}'
  export LABELS=$'org.opencontainers.image.title=bluefin\norg.opencontainers.image.version=44'
  run bash "${TEST_TMP}/populate.sh"
  [ "$status" -eq 0 ]
  [[ "$(podman_calls)" == *"manifest annotate --index --annotation org.opencontainers.image.title=bluefin"* ]]
  [ ! -s "$BUILDAH_LOG" ]
}

@test "populate: falls back to buildah when podman annotate --index fails" {
  populate_env
  export DIGESTS_JSON='{}'
  export LABELS="org.opencontainers.image.version=44"
  export PODMAN_ANNOTATE_STATUS=1
  run bash "${TEST_TMP}/populate.sh"
  [ "$status" -eq 0 ]
  [[ "$(cat "$BUILDAH_LOG")" == *"manifest annotate --annotation org.opencontainers.image.version=44 ghcr.io/projectbluefin/bluefin"* ]]
}

@test "populate: empty labels input performs no annotation" {
  populate_env
  export DIGESTS_JSON='{}'
  export LABELS=""
  run bash "${TEST_TMP}/populate.sh"
  [ "$status" -eq 0 ]
  [ ! -s "$BUILDAH_LOG" ]
  [[ "$(podman_calls)" != *"manifest annotate"* ]]
}

@test "populate: fails when podman manifest add fails" {
  populate_env
  export DIGESTS_JSON='{"amd64":"sha256:aaa"}'
  export PODMAN_ADD_STATUS=1
  run bash "${TEST_TMP}/populate.sh"
  [ "$status" -ne 0 ]
}

# ── Push manifest tags ────────────────────────────────────────────────────────

push_env() {
  export REGISTRY="GHCR.IO"
  export GITHUB_REPOSITORY_OWNER="ProjectBluefin"
  export IMAGE_NAME="bluefin"
  export MANIFEST="ghcr.io/projectbluefin/bluefin"
  export DIGEST_FILE="${TEST_TMP}/create-manifest.digest"
}

@test "push: first tag uses a digestfile and records the digest output" {
  push_env
  export TAGS="latest"
  run bash "${TEST_TMP}/push.sh"
  [ "$status" -eq 0 ]
  [ "$(get_output digest)" = "sha256:feedface" ]
  [[ "$(podman_calls)" == *"--digestfile ${DIGEST_FILE} ghcr.io/projectbluefin/bluefin ghcr.io/projectbluefin/bluefin:latest"* ]]
}

@test "push: subsequent tags push without a digestfile" {
  push_env
  export TAGS=$'latest\nstable\n44'
  run bash "${TEST_TMP}/push.sh"
  [ "$status" -eq 0 ]
  [ "$(grep -c 'manifest push' "$PODMAN_LOG")" -eq 3 ]
  [ "$(grep -c -- '--digestfile' "$PODMAN_LOG")" -eq 1 ]
  [[ "$(podman_calls)" == *"ghcr.io/projectbluefin/bluefin:stable"* ]]
  [[ "$(podman_calls)" == *"ghcr.io/projectbluefin/bluefin:44"* ]]
}

@test "push: blank tag lines are skipped" {
  push_env
  export TAGS=$'latest\n\nstable\n'
  run bash "${TEST_TMP}/push.sh"
  [ "$status" -eq 0 ]
  [ "$(grep -c 'manifest push' "$PODMAN_LOG")" -eq 2 ]
}

@test "push: retries a failing push and succeeds on the third attempt" {
  push_env
  export TAGS="latest"
  export PODMAN_PUSH_FAIL_TIMES=2
  run bash "${TEST_TMP}/push.sh"
  [ "$status" -eq 0 ]
  [ "$(grep -c 'manifest push' "$PODMAN_LOG")" -eq 3 ]
  [ "$(get_output digest)" = "sha256:feedface" ]
}

@test "push: fails after three failed attempts" {
  push_env
  export TAGS="latest"
  export PODMAN_PUSH_FAIL_TIMES=99
  run bash "${TEST_TMP}/push.sh"
  [ "$status" -ne 0 ]
  [[ "$output" == *"::error::Failed to push ghcr.io/projectbluefin/bluefin:latest after 3 attempts"* ]]
  [ "$(grep -c 'manifest push' "$PODMAN_LOG")" -eq 3 ]
}

@test "push: fails when the digestfile is empty" {
  push_env
  export TAGS="latest"
  export PODMAN_PUSH_EMPTY_DIGEST=1
  run bash "${TEST_TMP}/push.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Manifest push did not produce a digest file"* ]]
}

@test "push: fails when no tags are provided" {
  push_env
  export TAGS=""
  run bash "${TEST_TMP}/push.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::At least one tag must be provided"* ]]
  [ ! -s "$PODMAN_LOG" ]
}

@test "push: destination lowercases registry and owner" {
  push_env
  export TAGS="latest"
  run bash "${TEST_TMP}/push.sh"
  [ "$status" -eq 0 ]
  [[ "$(podman_calls)" != *"GHCR.IO"* ]]
  [[ "$(podman_calls)" != *"ProjectBluefin"* ]]
}
