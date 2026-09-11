#!/usr/bin/env bats
# Tests for .github/actions/validate-pr-title/action.yml.
#
# The shell logic lives inline in the single `run:` block of
# validate-pr-title/action.yml. The snippet below is a verbatim copy of that
# block so this test breaks if the action logic changes without updating the
# test (same convention as tests/bats/test_preflight.bats).
#
# Covers:
#   - accepts every declared Conventional Commits type
#   - accepts an optional scope, including a scope containing a slash
#   - rejects an unknown type, a missing colon, an empty description and a
#     leading-space title
#   - a non-empty custom-pattern overrides the default
#   - an empty custom-pattern falls back to the default pattern
#   - the failure path emits a ::error:: annotation, echoes both the title and
#     the pattern in use, and exits 1
#   - the success path echoes the title and exits 0

# Snippet below is a byte-for-byte copy of the `run:` block in
# .github/actions/validate-pr-title/action.yml (quoted heredoc, so nothing is
# re-expanded at definition time).

VALIDATE_SNIPPET=$(cat <<'SNIP'
set -euo pipefail

PATTERN="${CUSTOM_PATTERN:-^(feat|fix|chore|docs|refactor|test|perf|ci|build|revert)(\(.+\))?: .+$}"

if echo "${PR_TITLE}" | grep -qP "${PATTERN}"; then
  echo "✅ PR title follows Conventional Commits: '${PR_TITLE}'"
else
  echo "::error::PR title does not follow Conventional Commits format."
  echo ""
  echo "  Title:    ${PR_TITLE}"
  echo "  Pattern:  ${PATTERN}"
  echo ""
  echo "Expected format:  <type>[optional scope]: <description>"
  echo ""
  echo "Valid types:  feat  fix  chore  docs  refactor  test  perf  ci  build  revert"
  echo ""
  echo "Examples:"
  echo "  feat: add Trivy CVE scanning action"
  echo "  fix(chunka): vendor Containerfile.splitter"
  echo "  chore(deps): bump actions/checkout to v4.2.0"
  echo "  docs: document SLSA Build L2 scope"
  echo "  ci: wire scan-image into reusable-build"
  echo ""
  echo "See: https://www.conventionalcommits.org/"
  exit 1
fi
SNIP
)

setup() {
  # The composite action always sets both env vars; custom-pattern defaults to
  # the empty string, so mirror that here.
  export CUSTOM_PATTERN=""
}

validate() {
  export PR_TITLE="$1"
  run bash -c "$VALIDATE_SNIPPET"
}

# ── Accepted titles ───────────────────────────────────────────────────────────

@test "accepts every declared Conventional Commits type" {
  for type in feat fix chore docs refactor test perf ci build revert; do
    validate "${type}: do the thing"
    [ "$status" -eq 0 ] || {
      echo "type '${type}' was rejected: $output"
      return 1
    }
  done
}

@test "accepts an optional scope" {
  validate "fix(chunka): vendor Containerfile.splitter"
  [ "$status" -eq 0 ]
  [[ "$output" == *"follows Conventional Commits"* ]]
}

@test "accepts a scope containing a slash" {
  validate "chore(deps): bump actions/checkout to v4.2.0"
  [ "$status" -eq 0 ]
}

@test "success output echoes the title back" {
  validate "docs: document SLSA Build L2 scope"
  [ "$status" -eq 0 ]
  [[ "$output" == *"'docs: document SLSA Build L2 scope'"* ]]
}

# ── Rejected titles ───────────────────────────────────────────────────────────

@test "rejects an unknown type" {
  validate "wip: half a thought"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::PR title does not follow Conventional Commits format."* ]]
}

@test "rejects a title with no colon" {
  validate "feat add Trivy CVE scanning action"
  [ "$status" -eq 1 ]
}

@test "rejects a title with an empty description" {
  validate "feat: "
  [ "$status" -eq 1 ]
}

@test "rejects a title with no space after the colon" {
  validate "feat:add scanning"
  [ "$status" -eq 1 ]
}

@test "rejects a leading-space title" {
  validate " feat: add scanning"
  [ "$status" -eq 1 ]
}

@test "failure output names the title and the pattern in use" {
  validate "wip: half a thought"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Title:    wip: half a thought"* ]]
  [[ "$output" == *"Pattern:  ^(feat|fix|chore|docs|refactor|test|perf|ci|build|revert)"* ]]
  [[ "$output" == *"https://www.conventionalcommits.org/"* ]]
}

# ── custom-pattern override ───────────────────────────────────────────────────

@test "a non-empty custom-pattern replaces the default" {
  export CUSTOM_PATTERN='^RELEASE: .+$'
  validate "RELEASE: stable-20260623"
  [ "$status" -eq 0 ]
}

@test "a non-empty custom-pattern rejects titles the default would accept" {
  export CUSTOM_PATTERN='^RELEASE: .+$'
  validate "feat: add Trivy CVE scanning action"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Pattern:  ^RELEASE: .+\$"* ]]
}

@test "an empty custom-pattern falls back to the default pattern" {
  export CUSTOM_PATTERN=""
  validate "ci: wire scan-image into reusable-build"
  [ "$status" -eq 0 ]
}

@test "an unset custom-pattern falls back to the default pattern" {
  unset CUSTOM_PATTERN
  validate "perf: shrink the layer"
  [ "$status" -eq 0 ]
}
