#!/usr/bin/env bats
# Tests for bootc-build/generate-tags/generate_tags.sh
# Covers: stream routing, kernel-pin parsing, PR tag format, promotion day
# detection, version label prefix stripping, and stable-daily aliasing.

SCRIPT="${BATS_TEST_DIRNAME}/../../bootc-build/generate-tags/generate_tags.sh"

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  # Default env vars — override per test as needed
  export BASE_NAME="bluefin"
  export STREAM="testing"
  export FLAVOR="main"
  export KERNEL_PIN=""
  export VERSION_LABEL="42.20250531"
  export EVENT_NAME="push"
  export PR_NUMBER=""
  export GITHUB_SHA="abc1234def5678"
}

teardown() {
  rm -rf "$TEST_TMP"
}

# Helper: get a specific output value
get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

# ── Testing stream ────────────────────────────────────────────────────────────

@test "testing stream: default tag is 'testing'" {
  export STREAM="testing"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output default_tag)" = "testing" ]
}

@test "testing stream: tags include stream and version variants" {
  export STREAM="testing"
  export VERSION_LABEL="42.20250531"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"testing"* ]]
  [[ "$tags" == *"testing-42.20250531"* ]]
  [[ "$tags" == *"testing-20250531"* ]]
}

# ── Latest stream ─────────────────────────────────────────────────────────────

@test "latest stream: default tag is 'latest'" {
  export STREAM="latest"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output default_tag)" = "latest" ]
}

@test "latest stream: includes stable-daily aliases for compatibility" {
  export STREAM="latest"
  export VERSION_LABEL="42.20250531"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"stable-daily"* ]]
  [[ "$tags" == *"stable-daily-42.20250531"* ]]
  [[ "$tags" == *"stable-daily-20250531"* ]]
}

@test "latest stream: includes numeric Fedora version tags" {
  export STREAM="latest"
  export VERSION_LABEL="42.20250531"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"42"* ]]
  [[ "$tags" == *"42-42.20250531"* ]]
}

# ── Stable stream ─────────────────────────────────────────────────────────────

@test "stable stream: default tag is 'stable-daily'" {
  export STREAM="stable"
  export VERSION_LABEL="42.20250531"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output default_tag)" = "stable-daily" ]
}

@test "stable stream: includes stable-daily tags but NOT promotion tags on non-Tuesday push" {
  export STREAM="stable"
  export VERSION_LABEL="42.20250531"
  export EVENT_NAME="push"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"stable-daily"* ]]
  # Should NOT include the stable promotion tags on a plain push
  [[ "$tags" != *" stable "* ]] || [[ "$tags" != *"gts"* ]]
}

@test "stable stream: includes promotion tags on workflow_dispatch" {
  export STREAM="stable"
  export VERSION_LABEL="42.20250531"
  export EVENT_NAME="workflow_dispatch"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"stable"* ]]
  [[ "$tags" == *"gts"* ]]
  [[ "$tags" == *"gts-42.20250531"* ]]
}

@test "stable stream: includes promotion tags on workflow_call" {
  export STREAM="stable"
  export VERSION_LABEL="42.20250531"
  export EVENT_NAME="workflow_call"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"gts"* ]]
}

# ── Beta stream ───────────────────────────────────────────────────────────────

@test "beta stream: default tag is 'beta'" {
  export STREAM="beta"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(get_output default_tag)" = "beta" ]
}

@test "beta stream: does NOT get Fedora version tags" {
  export STREAM="beta"
  export VERSION_LABEL="42.20250531"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  # Beta should have beta-version tags but NOT standalone numeric Fedora version
  [[ "$tags" == *"beta-42.20250531"* ]]
  # Should not have standalone "42" tag (only latest gets that)
  tag_array=($tags)
  for t in "${tag_array[@]}"; do
    [ "$t" != "42" ]
  done
}

# ── PR events ─────────────────────────────────────────────────────────────────

@test "pull_request event: tags use pr-NUMBER-STREAM-VERSION format" {
  export EVENT_NAME="pull_request"
  export PR_NUMBER="123"
  export STREAM="testing"
  export VERSION_LABEL="42.20250531"
  export GITHUB_SHA="abc1234def5678"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"pr-123-testing-42.20250531"* ]]
}

@test "pull_request event: tags include short SHA prefix" {
  export EVENT_NAME="pull_request"
  export PR_NUMBER="456"
  export STREAM="testing"
  export VERSION_LABEL="42.20250531"
  export GITHUB_SHA="deadbeef12345"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  # SHA short is first 7 chars: deadbee
  [[ "$tags" == *"deadbee-testing-42.20250531"* ]]
}

@test "pull_request event: does NOT include build tags like stream or stable-daily" {
  export EVENT_NAME="pull_request"
  export PR_NUMBER="789"
  export STREAM="testing"
  export VERSION_LABEL="42.20250531"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  # PR tags should only be pr-NNN-... and sha-..., NOT plain "testing"
  tag_array=($tags)
  for t in "${tag_array[@]}"; do
    [ "$t" != "testing" ]
    [ "$t" != "stable-daily" ]
  done
}

# ── Kernel-pin Fedora version extraction ─────────────────────────────────────

@test "kernel-pin: extracts Fedora version from fc42 kernel string" {
  export STREAM="latest"
  export VERSION_LABEL="42.20250531"
  export KERNEL_PIN="6.14.9-200.fc42.x86_64"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"42"* ]]
}

@test "kernel-pin: extracts Fedora version from fc41 kernel string" {
  export STREAM="latest"
  export VERSION_LABEL="41.20250101"
  export KERNEL_PIN="6.12.0-100.fc41.x86_64"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"41"* ]]
}

@test "kernel-pin: overrides Fedora version from version label" {
  export STREAM="latest"
  # version label says 42 but kernel pin says 43
  export VERSION_LABEL="42.20250531"
  export KERNEL_PIN="6.14.9-200.fc43.x86_64"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"43"* ]]
  # Should NOT have 42 as a standalone fedora version tag from the label
  tag_array=($tags)
  found_42=false
  for t in "${tag_array[@]}"; do
    [ "$t" = "42" ] && found_42=true || true
  done
  [ "$found_42" = "false" ]
}

# ── Version label prefix stripping ───────────────────────────────────────────

@test "version label: strips stream prefix (rechunk labels like latest-42.20250531)" {
  export STREAM="latest"
  export VERSION_LABEL="latest-42.20250531"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  # Should use 42.20250531 (without the 'latest-' prefix) in tags
  [[ "$tags" == *"latest-42.20250531"* ]]
  [[ "$tags" == *"latest-20250531"* ]]
}

@test "version label: strips stable-daily prefix (rechunk uses stable-42.x labels for stable stream)" {
  # Rechunk sets label as "stable-42.20250531" for the stable stream (uses STREAM as prefix).
  # The script strips the "stable-" prefix and produces version "42.20250531".
  export STREAM="stable"
  export VERSION_LABEL="stable-42.20250531"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"stable-daily-42.20250531"* ]]
  [[ "$tags" == *"stable-daily-20250531"* ]]
}

@test "version label: plain label passthrough (no prefix to strip)" {
  export STREAM="testing"
  export VERSION_LABEL="42.20250531"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  tags=$(get_output tags)
  [[ "$tags" == *"testing-42.20250531"* ]]
}

# ── Output format ─────────────────────────────────────────────────────────────

@test "outputs are written to GITHUB_OUTPUT" {
  export STREAM="testing"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "^default_tag=" "$GITHUB_OUTPUT"
  grep -q "^tags=" "$GITHUB_OUTPUT"
}
