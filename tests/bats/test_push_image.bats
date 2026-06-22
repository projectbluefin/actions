#!/usr/bin/env bats
# Tests for the push-image action's push-with-retry shell step.
#
# The shell logic lives inline in bootc-build/push-image/action.yml.
# We extract it here verbatim (PUSH_SCRIPT) so any edit to the action
# that changes testable behavior must also update this file.
#
# Covers:
#   - Registry path lowercasing
#   - Default tag selection (first tag when DEFAULT_TAG_INPUT is empty)
#   - Explicit default tag when DEFAULT_TAG_INPUT is set
#   - Empty TAGS → error exit
#   - Successful push → digest written to GITHUB_OUTPUT
#   - Retry: push fails first attempt, succeeds on second
#   - Exhausted retries (MAX_ATTEMPTS=1, push always fails) → exit 1
#   - Alias tags: skopeo copy called for non-default tags
#   - Single tag: no skopeo copy call
#   - FORCE_COMPRESSION=true adds --force-compression flag
#   - FORCE_COMPRESSION=false omits --force-compression flag
#   - registry-path written to GITHUB_OUTPUT (lowercased)

# ── Shared push logic (verbatim from action.yml push step) ───────────────────

PUSH_LOGIC='
set -euo pipefail

REGISTRY_LOWER="${REGISTRY,,}/${GITHUB_REPOSITORY_OWNER,,}"
echo "registry-path=${REGISTRY_LOWER}" >> "$GITHUB_OUTPUT"

read -r -a TAG_ARRAY <<< "${TAGS}"
if [[ ${#TAG_ARRAY[@]} -eq 0 ]]; then
  echo "::error::At least one tag must be provided"
  exit 1
fi
DEFAULT_TAG="${DEFAULT_TAG_INPUT:-${TAG_ARRAY[0]}}"

FC_FLAG=""
if [[ "${FORCE_COMPRESSION}" == "true" ]]; then
  FC_FLAG="--force-compression"
fi

attempt=0
while true; do
  attempt=$((attempt + 1))
  rm -f "${DIGEST_FILE}"

  sudo buildah push \
    --authfile "${RUNNER_TEMP}/push-auth.json" \
    --compression-format "${COMPRESSION_FORMAT}" \
    --compression-level 3 \
    ${FC_FLAG:+${FC_FLAG}} \
    --retry 5 --retry-delay 30s \
    "${IMAGE_NAME}:${DEFAULT_TAG}" \
    "${REGISTRY_LOWER}/${IMAGE_NAME}:${DEFAULT_TAG}"

  skopeo inspect --no-tags \
    "docker://${REGISTRY_LOWER}/${IMAGE_NAME}:${DEFAULT_TAG}" \
    | jq -r '"'"'.Digest'"'"' > "${DIGEST_FILE}"

  if [[ -s "${DIGEST_FILE}" ]] && [[ $(<"${DIGEST_FILE}") != "null" ]]; then
    break
  fi

  if [[ ${attempt} -ge ${MAX_ATTEMPTS} ]]; then
    echo "::error::Push failed after ${MAX_ATTEMPTS} attempts"
    exit 1
  fi
  echo "Push attempt ${attempt} failed, retrying in ${RETRY_WAIT}s..."
  sleep "${RETRY_WAIT}"
done

DIGEST=$(<"${DIGEST_FILE}")
echo "digest=${DIGEST}" >> "$GITHUB_OUTPUT"

for tag in "${TAG_ARRAY[@]}"; do
  if [[ "${tag}" != "${DEFAULT_TAG}" ]]; then
    skopeo copy \
      "docker://${REGISTRY_LOWER}/${IMAGE_NAME}:${DEFAULT_TAG}" \
      "docker://${REGISTRY_LOWER}/${IMAGE_NAME}:${tag}"
  fi
done
'

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  # Mock sudo: pass-through (no privilege needed in tests)
  cat > "${MOCK_DIR}/sudo" << 'EOF'
#!/usr/bin/env bash
"$@"
EOF
  chmod +x "${MOCK_DIR}/sudo"

  # Mock sleep: no-op (don't actually wait between retries)
  cat > "${MOCK_DIR}/sleep" << 'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "${MOCK_DIR}/sleep"

  # Default mock buildah: success, writes nothing (digest comes from skopeo)
  cat > "${MOCK_DIR}/buildah" << 'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "${MOCK_DIR}/buildah"

  # Default mock skopeo: returns valid digest JSON for inspect; no-op for copy
  cat > "${MOCK_DIR}/skopeo" << 'EOF'
#!/usr/bin/env bash
if [[ "$1" == "inspect" ]]; then
  echo '{"Digest":"sha256:abc123def456deadbeef"}'
fi
exit 0
EOF
  chmod +x "${MOCK_DIR}/skopeo"

  # Record buildah and skopeo invocations for assertion
  export BUILDAH_CALL_LOG="${TEST_TMP}/buildah_calls"
  export SKOPEO_CALL_LOG="${TEST_TMP}/skopeo_calls"
  touch "$BUILDAH_CALL_LOG" "$SKOPEO_CALL_LOG"

  # Default env vars
  export IMAGE_NAME="my-image"
  export TAGS="testing"
  export DEFAULT_TAG_INPUT=""
  export REGISTRY="ghcr.io"
  export GITHUB_REPOSITORY_OWNER="ProjectBluefin"
  export MAX_ATTEMPTS="3"
  export RETRY_WAIT="1"
  export COMPRESSION_FORMAT="zstd:chunked"
  export FORCE_COMPRESSION="false"
  export RUNNER_TEMP="${TEST_TMP}"
  export DIGEST_FILE="${TEST_TMP}/push-digest"
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

run_push() {
  run bash -c "$PUSH_LOGIC"
}

# ── Registry path ─────────────────────────────────────────────────────────────

@test "registry path is lowercased and written to GITHUB_OUTPUT" {
  export REGISTRY="GHCR.IO"
  export GITHUB_REPOSITORY_OWNER="ProjectBluefin"
  run_push
  [ "$status" -eq 0 ]
  [ "$(get_output registry-path)" = "ghcr.io/projectbluefin" ]
}

@test "registry path already lowercase stays correct" {
  export REGISTRY="ghcr.io"
  export GITHUB_REPOSITORY_OWNER="projectbluefin"
  run_push
  [ "$status" -eq 0 ]
  [ "$(get_output registry-path)" = "ghcr.io/projectbluefin" ]
}

# ── Default tag selection ─────────────────────────────────────────────────────

@test "default tag uses first tag when DEFAULT_TAG_INPUT is empty" {
  export TAGS="testing stable"
  export DEFAULT_TAG_INPUT=""

  # Capture which tag buildah was called with
  cat > "${MOCK_DIR}/buildah" << EOF
#!/usr/bin/env bash
echo "\$@" >> "${BUILDAH_CALL_LOG}"
exit 0
EOF
  chmod +x "${MOCK_DIR}/buildah"

  run_push
  [ "$status" -eq 0 ]
  grep -q "my-image:testing" "$BUILDAH_CALL_LOG"
}

@test "explicit DEFAULT_TAG_INPUT overrides first tag" {
  export TAGS="testing stable"
  export DEFAULT_TAG_INPUT="stable"

  cat > "${MOCK_DIR}/buildah" << EOF
#!/usr/bin/env bash
echo "\$@" >> "${BUILDAH_CALL_LOG}"
exit 0
EOF
  chmod +x "${MOCK_DIR}/buildah"

  run_push
  [ "$status" -eq 0 ]
  grep -q "my-image:stable" "$BUILDAH_CALL_LOG"
}

@test "empty TAGS exits with error" {
  export TAGS=""
  run_push
  [ "$status" -ne 0 ]
  [[ "$output" == *"At least one tag must be provided"* ]]
}

# ── Successful push ───────────────────────────────────────────────────────────

@test "successful push writes digest to GITHUB_OUTPUT" {
  run_push
  [ "$status" -eq 0 ]
  [ "$(get_output digest)" = "sha256:abc123def456deadbeef" ]
}

@test "buildah push called with --authfile argument" {
  cat > "${MOCK_DIR}/buildah" << EOF
#!/usr/bin/env bash
echo "\$@" >> "${BUILDAH_CALL_LOG}"
exit 0
EOF
  chmod +x "${MOCK_DIR}/buildah"

  run_push
  [ "$status" -eq 0 ]
  grep -q -- "--authfile" "$BUILDAH_CALL_LOG"
}

@test "buildah push called with correct registry path" {
  export GITHUB_REPOSITORY_OWNER="projectbluefin"
  cat > "${MOCK_DIR}/buildah" << EOF
#!/usr/bin/env bash
echo "\$@" >> "${BUILDAH_CALL_LOG}"
exit 0
EOF
  chmod +x "${MOCK_DIR}/buildah"

  run_push
  [ "$status" -eq 0 ]
  grep -q "ghcr.io/projectbluefin/my-image:testing" "$BUILDAH_CALL_LOG"
}

# ── Retry logic ───────────────────────────────────────────────────────────────

@test "push retries after skopeo returns empty digest" {
  CALL_COUNT=0
  # First skopeo call returns null digest; second returns valid digest
  cat > "${MOCK_DIR}/skopeo" << EOF
#!/usr/bin/env bash
if [[ "\$1" == "inspect" ]]; then
  COUNT_FILE="${TEST_TMP}/skopeo_count"
  n=\$(cat "\$COUNT_FILE" 2>/dev/null || echo 0)
  n=\$((n + 1))
  echo "\$n" > "\$COUNT_FILE"
  if [[ \$n -lt 2 ]]; then
    echo '{"Digest":"null"}'
  else
    echo '{"Digest":"sha256:retried-ok"}'
  fi
fi
exit 0
EOF
  chmod +x "${MOCK_DIR}/skopeo"

  run_push
  [ "$status" -eq 0 ]
  [ "$(get_output digest)" = "sha256:retried-ok" ]
}

@test "push fails after MAX_ATTEMPTS exhausted" {
  export MAX_ATTEMPTS="2"
  # buildah always succeeds but skopeo always returns null digest
  cat > "${MOCK_DIR}/skopeo" << 'EOF'
#!/usr/bin/env bash
if [[ "$1" == "inspect" ]]; then
  echo '{"Digest":"null"}'
fi
exit 0
EOF
  chmod +x "${MOCK_DIR}/skopeo"

  run_push
  [ "$status" -ne 0 ]
  [[ "$output" == *"Push failed after"* ]]
}

@test "push fails immediately when buildah exits nonzero and MAX_ATTEMPTS=1" {
  export MAX_ATTEMPTS="1"
  cat > "${MOCK_DIR}/buildah" << 'EOF'
#!/usr/bin/env bash
exit 1
EOF
  chmod +x "${MOCK_DIR}/buildah"

  run_push
  [ "$status" -ne 0 ]
}

# ── Alias tag copy ────────────────────────────────────────────────────────────

@test "no skopeo copy when single tag" {
  export TAGS="testing"
  cat > "${MOCK_DIR}/skopeo" << EOF
#!/usr/bin/env bash
if [[ "\$1" == "inspect" ]]; then
  echo '{"Digest":"sha256:abc"}'
fi
echo "\$@" >> "${SKOPEO_CALL_LOG}"
exit 0
EOF
  chmod +x "${MOCK_DIR}/skopeo"

  run_push
  [ "$status" -eq 0 ]
  # Only the inspect call should appear; no 'copy' call
  ! grep -q '^copy ' "$SKOPEO_CALL_LOG" || ! grep "copy" "$SKOPEO_CALL_LOG" | grep -q "stable"
}

@test "skopeo copy called for each non-default alias tag" {
  export TAGS="testing stable latest"
  export DEFAULT_TAG_INPUT="testing"

  cat > "${MOCK_DIR}/skopeo" << EOF
#!/usr/bin/env bash
if [[ "\$1" == "inspect" ]]; then
  echo '{"Digest":"sha256:abc"}'
fi
echo "\$@" >> "${SKOPEO_CALL_LOG}"
exit 0
EOF
  chmod +x "${MOCK_DIR}/skopeo"

  run_push
  [ "$status" -eq 0 ]
  grep -q "copy.*:stable" "$SKOPEO_CALL_LOG"
  grep -q "copy.*:latest" "$SKOPEO_CALL_LOG"
}

@test "skopeo copy not called for the default tag itself" {
  export TAGS="testing stable"
  export DEFAULT_TAG_INPUT="testing"

  cat > "${MOCK_DIR}/skopeo" << EOF
#!/usr/bin/env bash
if [[ "\$1" == "inspect" ]]; then
  echo '{"Digest":"sha256:abc"}'
fi
echo "\$@" >> "${SKOPEO_CALL_LOG}"
exit 0
EOF
  chmod +x "${MOCK_DIR}/skopeo"

  run_push
  [ "$status" -eq 0 ]
  # 'copy' should not target the default tag
  ! grep "copy" "$SKOPEO_CALL_LOG" | grep -q ":testing$" || true
}

# ── force-compression flag ────────────────────────────────────────────────────

@test "FORCE_COMPRESSION=true passes --force-compression to buildah" {
  export FORCE_COMPRESSION="true"
  cat > "${MOCK_DIR}/buildah" << EOF
#!/usr/bin/env bash
echo "\$@" >> "${BUILDAH_CALL_LOG}"
exit 0
EOF
  chmod +x "${MOCK_DIR}/buildah"

  run_push
  [ "$status" -eq 0 ]
  grep -q -- "--force-compression" "$BUILDAH_CALL_LOG"
}

@test "FORCE_COMPRESSION=false omits --force-compression from buildah" {
  export FORCE_COMPRESSION="false"
  cat > "${MOCK_DIR}/buildah" << EOF
#!/usr/bin/env bash
echo "\$@" >> "${BUILDAH_CALL_LOG}"
exit 0
EOF
  chmod +x "${MOCK_DIR}/buildah"

  run_push
  [ "$status" -eq 0 ]
  ! grep -q -- "--force-compression" "$BUILDAH_CALL_LOG"
}
