#!/usr/bin/env bats
# Tests for the "Compute push tags" step in .github/workflows/reusable-build.yml.
#
# The shell logic lives inline in the workflow. We extract it here verbatim
# (COMPUTE_LOGIC) so any edit to the workflow that changes testable behavior
# must also update this file.
#
# Regression guard for the stream-tag leak: `just generate-build-tags` emits the
# bare stream tag (e.g. "testing") as the first alias tag, so publishing
# ALIAS_TAGS unchanged while publish_stream_tag=false pushed an ungated
# :testing pointer.
#
# Covers:
#   - publish_stream_tag=true keeps the historical push list verbatim
#   - publish_stream_tag=false drops the bare stream tag from push_tags
#   - publish_stream_tag=false drops stable-daily (DEFAULT_TAG) and stable
#   - publish_stream_tag=false picks a non-stream tag as push_default
#   - publish_stream_tag=false with only stream tags → error exit
#   - invalid publish_stream_tag values fail closed

COMPUTE_LOGIC='
set -euo pipefail
if [[ "${PUBLISH_STREAM_TAG}" != "true" && "${PUBLISH_STREAM_TAG}" != "false" ]]; then
  echo "::error::publish_stream_tag must be exactly \"true\" or \"false\" (got: '"'"'${PUBLISH_STREAM_TAG}'"'"')"
  exit 1
fi

if [[ "${PUBLISH_STREAM_TAG}" == "true" ]]; then
  echo "push_default=${DEFAULT_TAG}" >> "$GITHUB_OUTPUT"
  echo "push_tags=${DEFAULT_TAG} ${ALIAS_TAGS}" >> "$GITHUB_OUTPUT"
  exit 0
fi

read -r -a ALIAS_ARR <<< "${ALIAS_TAGS}"
GATED_TAGS=()
for tag in ${ALIAS_ARR[@]+"${ALIAS_ARR[@]}"}; do
  if [[ "${tag}" == "${DEFAULT_TAG}" || "${tag}" == "${STREAM_NAME}" ]]; then
    continue
  fi
  GATED_TAGS+=("${tag}")
done

if [[ ${#GATED_TAGS[@]} -eq 0 ]]; then
  echo "::error::publish_stream_tag=false but no non-stream alias tags are available — cannot push"
  exit 1
fi

for tag in "${GATED_TAGS[@]}"; do
  if [[ "${tag}" == "${DEFAULT_TAG}" || "${tag}" == "${STREAM_NAME}" ]]; then
    echo "::error::stream tag '"'"'${tag}'"'"' leaked into push list while publish_stream_tag=false"
    exit 1
  fi
done

echo "push_default=${GATED_TAGS[0]}" >> "$GITHUB_OUTPUT"
echo "push_tags=${GATED_TAGS[*]}" >> "$GITHUB_OUTPUT"
echo "Stream tags (${DEFAULT_TAG}, ${STREAM_NAME}) excluded — promoted after e2e gate"
echo "Push tags: ${GATED_TAGS[*]}"
'

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  export DEFAULT_TAG="testing"
  export STREAM_NAME="testing"
  export ALIAS_TAGS="testing testing-44.20260804 testing-20260804"
  export PUBLISH_STREAM_TAG="false"
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

run_compute() {
  run bash -c "$COMPUTE_LOGIC"
}

# ── publish_stream_tag=true (default consumers) ──────────────────────────────

@test "publish_stream_tag=true pushes the stream tag first" {
  export PUBLISH_STREAM_TAG="true"
  run_compute
  [ "$status" -eq 0 ]
  [ "$(get_output push_default)" = "testing" ]
  [ "$(get_output push_tags)" = "testing testing testing-44.20260804 testing-20260804" ]
}

@test "publish_stream_tag=true on a stable stream keeps stable-daily default" {
  export PUBLISH_STREAM_TAG="true"
  export DEFAULT_TAG="stable-daily"
  export STREAM_NAME="stable"
  export ALIAS_TAGS="stable-daily 44.20260804 stable"
  run_compute
  [ "$status" -eq 0 ]
  [ "$(get_output push_default)" = "stable-daily" ]
  [ "$(get_output push_tags)" = "stable-daily stable-daily 44.20260804 stable" ]
}

# ── publish_stream_tag=false (gated consumers) ───────────────────────────────

@test "publish_stream_tag=false drops the bare stream tag from push_tags" {
  run_compute
  [ "$status" -eq 0 ]
  [ "$(get_output push_tags)" = "testing-44.20260804 testing-20260804" ]
}

@test "publish_stream_tag=false does not use the stream tag as push_default" {
  run_compute
  [ "$status" -eq 0 ]
  [ "$(get_output push_default)" = "testing-44.20260804" ]
}

@test "publish_stream_tag=false drops both stable-daily and stable pointers" {
  export DEFAULT_TAG="stable-daily"
  export STREAM_NAME="stable"
  export ALIAS_TAGS="stable-daily 44.20260804 stable-daily-44.20260804 stable"
  run_compute
  [ "$status" -eq 0 ]
  [ "$(get_output push_tags)" = "44.20260804 stable-daily-44.20260804" ]
  [ "$(get_output push_default)" = "44.20260804" ]
}

@test "publish_stream_tag=false keeps PR commit tags untouched" {
  export ALIAS_TAGS="pr-123-testing-44.20260804 abc1234-testing-44.20260804"
  run_compute
  [ "$status" -eq 0 ]
  [ "$(get_output push_tags)" = "pr-123-testing-44.20260804 abc1234-testing-44.20260804" ]
}

@test "publish_stream_tag=false errors when only stream tags exist" {
  export ALIAS_TAGS="testing"
  run_compute
  [ "$status" -eq 1 ]
  [[ "$output" == *"no non-stream alias tags are available"* ]]
}

@test "publish_stream_tag=false errors on an empty alias tag list" {
  export ALIAS_TAGS=""
  run_compute
  [ "$status" -eq 1 ]
  [[ "$output" == *"no non-stream alias tags are available"* ]]
}

# ── Fail-closed validation ───────────────────────────────────────────────────

@test "invalid publish_stream_tag value fails closed" {
  export PUBLISH_STREAM_TAG="True"
  run_compute
  [ "$status" -eq 1 ]
  [[ "$output" == *"must be exactly"* ]]
}

@test "empty publish_stream_tag value fails closed" {
  export PUBLISH_STREAM_TAG=""
  run_compute
  [ "$status" -eq 1 ]
  [[ "$output" == *"must be exactly"* ]]
}
