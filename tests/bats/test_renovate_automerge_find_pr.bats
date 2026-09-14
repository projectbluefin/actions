#!/usr/bin/env bats
# Tests for the PR-lookup / qualification matcher in
# .github/workflows/reusable-renovate-automerge.yml ("Find qualifying
# Renovate PR for this commit" step, id: find-pr).
#
# The shell logic lives inline in the workflow YAML. It is captured here
# verbatim (FIND_PR_LOGIC) so any edit to the step that changes testable
# behavior must also update this file.
#
# This is the step the auto-merge issue (#403) flags as never exercised
# end-to-end: every production run has logged "No qualifying
# Renovate/Mergeraptor PR — skipping", so the matcher has only ever seen an
# empty result set. These tests exercise the matcher against every login
# spelling and every gate so a regression cannot silently re-skip a real
# qualifying PR.
#
# Covers:
#   - the GraphQL author.login spellings are all normalised and matched:
#     bare "mergeraptor" (GraphQL), "app/mergeraptor" (REST), "renovate[bot]"
#     (legacy bot)
#   - HEAD_SHA must match the PR head before it qualifies
#   - draft PRs never qualify
#   - CONFLICTING PRs never qualify
#   - require_auto_merge=true drops PRs whose autoMergeRequest is null
#   - require_auto_merge=false merges a bot PR even when autoMergeRequest is null
#   - human authors never qualify
#   - when several PRs match, the first (head -1) wins
#   - nothing matching logs the skip message and writes an empty pr_number

# --- Verbatim run block from reusable-renovate-automerge.yml (id: find-pr) ---
FIND_PR_LOGIC=$(cat <<'EOF'
set -euo pipefail

nodes=$(gh api graphql \
  -f owner="${GITHUB_REPOSITORY%/*}" \
  -f repo="${GITHUB_REPOSITORY#*/}" \
  -f base="$BASE_BRANCH" \
  -f query='
    query($owner: String!, $repo: String!, $base: String!) {
      repository(owner: $owner, name: $repo) {
        pullRequests(first: 100, states: OPEN, baseRefName: $base) {
          nodes {
            number
            isDraft
            mergeable
            headRefOid
            author { login }
            autoMergeRequest { enabledAt }
          }
        }
      }
    }' \
  --jq '.data.repository.pullRequests.nodes')

pr_number=$(jq -r \
  --arg head "$HEAD_SHA" \
  --arg require "$REQUIRE_AUTO_MERGE" '
    .[]
    | select(.headRefOid == $head)
    | select(.isDraft | not)
    | select(.mergeable != "CONFLICTING")
    | select((.author.login | ascii_downcase | sub("^app/"; "") | sub("\\[bot\\]$"; ""))
             | . == "mergeraptor" or . == "renovate")
    | select($require != "true" or .autoMergeRequest != null)
    | .number' <<<"$nodes" | head -1)

if [ -z "$pr_number" ]; then
  echo "No qualifying Renovate/Mergeraptor PR for SHA $HEAD_SHA on base $BASE_BRANCH — skipping"
else
  echo "Found qualifying PR #$pr_number"
fi
echo "pr_number=$pr_number" >> "$GITHUB_OUTPUT"
EOF
)

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"
  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  export GITHUB_REPOSITORY="projectbluefin/actions"
  export BASE_BRANCH="main"
  export HEAD_SHA="0123456789abcdef0123456789abcdef"
  export REQUIRE_AUTO_MERGE="true"
  # Default: no PRs match. Tests set NODES_JSON to a populated PR list.
  export NODES_JSON='[]'

  # gh mock: the real `gh api graphql ... --jq '.data.repository.pullRequests.nodes'`
  # emits the nodes array; echo the staged value regardless of the -f flags.
  cat > "${MOCK_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "api graphql")
    printf '%s\n' "$NODES_JSON"
    ;;
  *)
    echo "mock gh: unexpected invocation: $*" >&2
    exit 1
    ;;
esac
EOF
  chmod +x "${MOCK_DIR}/gh"
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | head -1 | cut -d= -f2-
}

# Build a nodes JSON array from records. Each arg is a jq object literal.
nodes_json() {
  local json='[]' rec
  for rec in "$@"; do
    json=$(jq --argjson r "$rec" '. + [$r]' <<<"$json")
  done
  printf '%s\n' "$json"
}

rec() {
  # rec <number> <headRefOid> <author> <isDraft> <mergeable> <autoMerge|null>
  jq -n \
    --argjson number "$1" \
    --arg head "$2" \
    --arg author "$3" \
    --argjson isDraft "$4" \
    --arg mergeable "$5" \
    --argjson am "$6" \
    '{number: $number, headRefOid: $head, author: {login: $author}, isDraft: $isDraft, mergeable: $mergeable, autoMergeRequest: ($am | if . == null then null else {enabledAt: "2026-01-01T00:00:00Z"} end)}'
}

found_pr() {
  get_output pr_number
}

@test "GraphQL bare-slug mergeraptor author with autoMergeRequest qualifies" {
  NODES_JSON=$(nodes_json "$(rec 10 "$HEAD_SHA" mergeraptor false SUCCESS true)")
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Found qualifying PR #10"* ]]
  [ "$(found_pr)" = "10" ]
}

@test "REST spelling app/mergeraptor is normalised and qualifies" {
  NODES_JSON=$(nodes_json "$(rec 11 "$HEAD_SHA" app/mergeraptor false SUCCESS true)")
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Found qualifying PR #11"* ]]
  [ "$(found_pr)" = "11" ]
}

@test "legacy renovate[bot] spelling is normalised and qualifies" {
  NODES_JSON=$(nodes_json "$(rec 12 "$HEAD_SHA" renovate[bot] false SUCCESS true)")
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Found qualifying PR #12"* ]]
  [ "$(found_pr)" = "12" ]
}

@test "require_auto_merge drops a bot PR with null autoMergeRequest" {
  NODES_JSON=$(nodes_json "$(rec 13 "$HEAD_SHA" mergeraptor false SUCCESS null)")
  export REQUIRE_AUTO_MERGE="true"
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No qualifying Renovate/Mergeraptor PR"* ]]
  [ "$(found_pr)" = "" ]
}

@test "require_auto_merge=false merges a bot PR even with null autoMergeRequest" {
  NODES_JSON=$(nodes_json "$(rec 14 "$HEAD_SHA" mergeraptor false SUCCESS null)")
  export REQUIRE_AUTO_MERGE="false"
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Found qualifying PR #14"* ]]
  [ "$(found_pr)" = "14" ]
}

@test "draft PR never qualifies" {
  NODES_JSON=$(nodes_json "$(rec 15 "$HEAD_SHA" mergeraptor true SUCCESS true)")
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No qualifying Renovate/Mergeraptor PR"* ]]
  [ "$(found_pr)" = "" ]
}

@test "conflicting PR never qualifies" {
  NODES_JSON=$(nodes_json "$(rec 16 "$HEAD_SHA" mergeraptor false CONFLICTING true)")
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No qualifying Renovate/Mergeraptor PR"* ]]
  [ "$(found_pr)" = "" ]
}

@test "HEAD_SHA must match the PR head to qualify" {
  NODES_JSON=$(nodes_json "$(rec 17 "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef" mergeraptor false SUCCESS true)")
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No qualifying Renovate/Mergeraptor PR"* ]]
  [ "$(found_pr)" = "" ]
}

@test "human authors never qualify" {
  NODES_JSON=$(nodes_json "$(rec 18 "$HEAD_SHA" castrojo false SUCCESS true)")
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No qualifying Renovate/Mergeraptor PR"* ]]
  [ "$(found_pr)" = "" ]
}

@test "when several PRs match, the first one wins" {
  NODES_JSON=$(nodes_json \
    "$(rec 20 "$HEAD_SHA" mergeraptor false SUCCESS true)" \
    "$(rec 21 "$HEAD_SHA" renovate[bot] false SUCCESS true)")
  run bash -c "$FIND_PR_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(found_pr)" = "20" ]
}
