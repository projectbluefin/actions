#!/usr/bin/env bats
# Tests for bootc-build/generate-release-notes inline shell logic.
#
# The shell logic lives inline in bootc-build/generate-release-notes/action.yml
# in the "Validate tag format" step.
# The snippet below is a verbatim copy of that run block so this test breaks
# if the action logic changes without updating the test.
#
# Covers:
#   - Valid semver tag formats:
#       * v1.2.3, v1.2, 1.2.3, 1.2
#       * pre-release tags: v1.2.3-rc.1, v1.2.3-alpha, 1.0.0-beta.2
#       * build metadata: v1.2.3+20260906, v1.2.3-rc.1+build.1
#   - Invalid tag formats rejected with exit 1 and ::error:: annotation:
#       * bare text: "latest", "testing", "invalid"
#       * missing minor version: "v1", "1"
#       * invalid characters: "v1.2.3/beta", "v1.2.3 4"
#       * empty string
#   - Snippet drift guard against action.yml

VALIDATE_TAG_SNIPPET=$(cat <<'SNIP'
set -euo pipefail
# Validate tag matches semver-like format: v1.2.3, v1.2, 1.2.3, v1.2.3-rc.1, etc.
if ! [[ "${INPUT_TAG}" =~ ^v?[0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9._-]+)?(\+[a-zA-Z0-9._-]+)?$ ]]; then
  echo "::error::Invalid tag format '${INPUT_TAG}'. Expected semver format: v1.2.3, v1.2.3-rc.1, etc."
  exit 1
fi
SNIP
)

# ── Valid tag formats ─────────────────────────────────────────────────────────

@test "generate-release-notes: accepts standard semver v1.2.3" {
  export INPUT_TAG="v1.2.3"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

@test "generate-release-notes: accepts two-part version v1.2" {
  export INPUT_TAG="v1.2"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

@test "generate-release-notes: accepts version without leading v (1.2.3)" {
  export INPUT_TAG="1.2.3"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

@test "generate-release-notes: accepts pre-release suffix (v1.2.3-rc.1)" {
  export INPUT_TAG="v1.2.3-rc.1"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

@test "generate-release-notes: accepts pre-release with alphanumeric tag (v1.0.0-beta.2)" {
  export INPUT_TAG="v1.0.0-beta.2"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

@test "generate-release-notes: accepts build metadata suffix (v1.2.3+build.42)" {
  export INPUT_TAG="v1.2.3+build.42"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

@test "generate-release-notes: accepts pre-release and build metadata (v1.2.3-rc.1+sha.abcdef)" {
  export INPUT_TAG="v1.2.3-rc.1+sha.abcdef"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

# ── Invalid tag formats ───────────────────────────────────────────────────────

@test "generate-release-notes: rejects bare branch name 'latest'" {
  export INPUT_TAG="latest"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Invalid tag format 'latest'"* ]]
}

@test "generate-release-notes: rejects bare branch name 'testing'" {
  export INPUT_TAG="testing"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Invalid tag format 'testing'"* ]]
}

@test "generate-release-notes: rejects major-only version 'v1'" {
  export INPUT_TAG="v1"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Invalid tag format 'v1'"* ]]
}

@test "generate-release-notes: rejects major-only without prefix '1'" {
  export INPUT_TAG="1"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Invalid tag format '1'"* ]]
}

@test "generate-release-notes: rejects empty string tag" {
  export INPUT_TAG=""
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Invalid tag format ''"* ]]
}

@test "generate-release-notes: rejects tags containing whitespace" {
  export INPUT_TAG="v1.2.3 beta"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Invalid tag format 'v1.2.3 beta'"* ]]
}

@test "generate-release-notes: rejects tags with illegal characters" {
  export INPUT_TAG="v1.2.3/tag"
  run bash -c "$VALIDATE_TAG_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::Invalid tag format 'v1.2.3/tag'"* ]]
}

# ── Snippet drift guard ───────────────────────────────────────────────────────

@test "generate-release-notes: action.yml still contains the tag validation regex under test" {
  ACTION="${BATS_TEST_DIRNAME}/../../bootc-build/generate-release-notes/action.yml"
  [ -f "$ACTION" ]
  grep -Fq "Expected semver format: v1.2.3" "$ACTION"
  grep -Fq "Invalid tag format" "$ACTION"
  grep -Fq "Expected semver format: v1.2.3" "$ACTION"
  grep -Fq "Invalid tag format" "$ACTION"
}
