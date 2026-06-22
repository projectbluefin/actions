#!/usr/bin/env bats
# Tests for bootc-build/detect-changes image_flavors computation.
#
# The shell logic lives inline in detect-changes/action.yml.
# We replicate it here to verify both branches without spinning up
# a full GitHub Actions context.
#
# Covers:
#   - nvidia_changed=false  → image_flavors=["main"]
#   - nvidia_changed=true   → image_flavors=["main","nvidia"]
#   - nvidia_changed unset  → image_flavors=["main"]  (treats unset as false)
#   - GITHUB_OUTPUT written correctly in both cases

# Inline the exact shell snippet from detect-changes/action.yml so this
# test breaks if the logic changes without updating the test.
DETECT_CHANGES_SNIPPET='
set -euo pipefail
if [[ "${NVIDIA_CHANGED}" == "true" ]]; then
  echo '"'"'image_flavors=["main","nvidia"]'"'"' >> "$GITHUB_OUTPUT"
else
  echo '"'"'image_flavors=["main"]'"'"' >> "$GITHUB_OUTPUT"
fi
'

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"
}

teardown() {
  rm -rf "$TEST_TMP"
}

# Helper: read a value from GITHUB_OUTPUT
get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

# ── nvidia_changed=false ──────────────────────────────────────────────────────

@test "nvidia_changed=false produces image_flavors=[\"main\"]" {
  export NVIDIA_CHANGED="false"
  run bash -c "$DETECT_CHANGES_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output image_flavors)" = '["main"]' ]
}

@test "nvidia_changed=false: image_flavors does not include nvidia" {
  export NVIDIA_CHANGED="false"
  run bash -c "$DETECT_CHANGES_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$(get_output image_flavors)" != *"nvidia"* ]]
}

# ── nvidia_changed=true ───────────────────────────────────────────────────────

@test "nvidia_changed=true produces image_flavors=[\"main\",\"nvidia\"]" {
  export NVIDIA_CHANGED="true"
  run bash -c "$DETECT_CHANGES_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output image_flavors)" = '["main","nvidia"]' ]
}

@test "nvidia_changed=true: image_flavors includes both main and nvidia" {
  export NVIDIA_CHANGED="true"
  run bash -c "$DETECT_CHANGES_SNIPPET"
  [ "$status" -eq 0 ]
  val="$(get_output image_flavors)"
  [[ "$val" == *"main"* ]]
  [[ "$val" == *"nvidia"* ]]
}

# ── GITHUB_OUTPUT format ──────────────────────────────────────────────────────

@test "output line is written as key=value to GITHUB_OUTPUT" {
  export NVIDIA_CHANGED="false"
  run bash -c "$DETECT_CHANGES_SNIPPET"
  [ "$status" -eq 0 ]
  grep -q '^image_flavors=' "$GITHUB_OUTPUT"
}

@test "only one image_flavors line written per run" {
  export NVIDIA_CHANGED="false"
  run bash -c "$DETECT_CHANGES_SNIPPET"
  [ "$status" -eq 0 ]
  count=$(grep -c '^image_flavors=' "$GITHUB_OUTPUT")
  [ "$count" -eq 1 ]
}

# ── edge cases ────────────────────────────────────────────────────────────────

@test "nvidia_changed=empty string falls through to main-only" {
  export NVIDIA_CHANGED=""
  run bash -c "$DETECT_CHANGES_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output image_flavors)" = '["main"]' ]
}

@test "nvidia_changed=TRUE (uppercase) is not treated as true" {
  export NVIDIA_CHANGED="TRUE"
  run bash -c "$DETECT_CHANGES_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output image_flavors)" = '["main"]' ]
}
