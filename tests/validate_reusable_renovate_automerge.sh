#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH_ROOT="${ROOT_DIR}/tests/.scratch/reusable-renovate-automerge.$$"
ORIGINAL_PATH="$PATH"

cleanup() {
  rm -rf "$SCRATCH_ROOT"
}
trap cleanup EXIT

mkdir -p "$SCRATCH_ROOT"

read -r -d '' FIND_PR_LOGIC <<'EOF' || true
PR_NUMBER=$(gh api graphql -f query="
  query(\$owner: String!, \$repo: String!, \$base: String!) {
    repository(owner: \$owner, name: \$repo) {
      pullRequests(first: 100, states: OPEN, baseRefName: \$base) {
        nodes {
          number
          headRefOid
          author { login }
          autoMergeRequest {
            enabledAt
            enabledBy { login }
          }
        }
      }
    }
  }" \
  -f owner="${GITHUB_REPOSITORY_OWNER}" \
  -f repo="${GITHUB_REPOSITORY#*/}" \
  -f base="$BASE_BRANCH" \
  | jq -r --arg head "$HEAD_SHA" '.data.repository.pullRequests.nodes[]
    | select(.headRefOid == $head)
    | select(.author.login == "app/mergeraptor" or .author.login == "renovate[bot]")
    | select(.autoMergeRequest != null)
    | select(.autoMergeRequest.enabledBy != null)
    | select(.autoMergeRequest.enabledBy.login == "app/mergeraptor" or .autoMergeRequest.enabledBy.login == "renovate[bot]")
    | .number' | head -1)

if [ -z "$PR_NUMBER" ]; then
  echo "No eligible Renovate/Mergeraptor PR found for SHA $HEAD_SHA on base $BASE_BRANCH — skipping"
  echo "pr_number=" >> "$GITHUB_OUTPUT"
else
  echo "Found eligible Renovate/Mergeraptor PR #$PR_NUMBER"
  echo "pr_number=$PR_NUMBER" >> "$GITHUB_OUTPUT"
fi
EOF

read -r -d '' MERGE_LOGIC <<'EOF' || true
set +e
CHECKS=$(gh pr checks "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json bucket,name)
CHECKS_STATUS=$?
set -e

if [ "$CHECKS_STATUS" -ne 0 ] && [ "$CHECKS_STATUS" -ne 1 ] && [ "$CHECKS_STATUS" -ne 8 ]; then
  exit "$CHECKS_STATUS"
fi

if [ -z "$CHECKS" ] || ! jq -e 'type == "array"' >/dev/null 2>&1 <<<"$CHECKS"; then
  echo "Failed to read PR check rollup for PR #$PR_NUMBER" >&2
  exit 1
fi

if [ "$(jq 'length' <<<"$CHECKS")" -eq 0 ] ||
   [ "$(jq '[.[] | select(.bucket != "pass")] | length' <<<"$CHECKS")" -ne 0 ]; then
  echo "PR #$PR_NUMBER does not have a complete successful check rollup; skipping"
  exit 0
fi

gh pr merge "$PR_NUMBER" --squash --repo "$GITHUB_REPOSITORY"
echo "Merged PR #$PR_NUMBER"
EOF

fail() {
  echo "not ok - $1" >&2
  exit 1
}

pass() {
  echo "ok - $1"
}

assert_eq() {
  local actual="$1"
  local expected="$2"
  local message="$3"
  [[ "$actual" == "$expected" ]] || fail "${message}: expected '${expected}', got '${actual}'"
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  [[ "$haystack" == *"$needle"* ]] || fail "${message}: missing '${needle}'"
}

assert_file_empty() {
  local path="$1"
  local message="$2"
  [[ ! -s "$path" ]] || fail "$message"
}

assert_file_contains() {
  local path="$1"
  local needle="$2"
  local message="$3"
  grep -Fq "$needle" "$path" || fail "${message}: missing '${needle}'"
}

setup_case() {
  local case_name="$1"
  CASE_DIR="${SCRATCH_ROOT}/${case_name}"
  rm -rf "$CASE_DIR"
  mkdir -p "${CASE_DIR}/bin"

  export PATH="${CASE_DIR}/bin:${ORIGINAL_PATH}"
  export GITHUB_OUTPUT="${CASE_DIR}/github_output"
  export GITHUB_REPOSITORY_OWNER="projectbluefin"
  export GITHUB_REPOSITORY="projectbluefin/actions"
  export HEAD_SHA="deadbeef"
  export BASE_BRANCH="main"
  export PR_NUMBER="101"
  export MOCK_GRAPHQL_RESPONSE_FILE="${CASE_DIR}/graphql.json"
  export MOCK_CHECKS_RESPONSE_FILE="${CASE_DIR}/checks.json"
  export MOCK_MERGE_CALLS_FILE="${CASE_DIR}/merge_calls"
  export MOCK_CHECKS_EXIT_STATUS="0"
  export MOCK_MERGE_EXIT_STATUS="0"

  : > "$GITHUB_OUTPUT"
  : > "$MOCK_GRAPHQL_RESPONSE_FILE"
  : > "$MOCK_CHECKS_RESPONSE_FILE"
  : > "$MOCK_MERGE_CALLS_FILE"

  cat > "${CASE_DIR}/bin/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$1" == "api" && "$2" == "graphql" ]]; then
  cat "$MOCK_GRAPHQL_RESPONSE_FILE"
  exit 0
fi

if [[ "$1" == "pr" && "$2" == "checks" ]]; then
  cat "$MOCK_CHECKS_RESPONSE_FILE"
  exit "$MOCK_CHECKS_EXIT_STATUS"
fi

if [[ "$1" == "pr" && "$2" == "merge" ]]; then
  printf '%s\n' "$*" >> "$MOCK_MERGE_CALLS_FILE"
  exit "$MOCK_MERGE_EXIT_STATUS"
fi

echo "unexpected gh invocation: $*" >&2
exit 99
EOF
  chmod +x "${CASE_DIR}/bin/gh"
}

run_snippet() {
  local snippet="$1"
  local stdout_file="${CASE_DIR}/stdout"
  local stderr_file="${CASE_DIR}/stderr"

  set +e
  bash -c "$snippet" >"$stdout_file" 2>"$stderr_file"
  RUN_STATUS=$?
  set -e

  RUN_STDOUT="$(<"$stdout_file")"
  RUN_STDERR="$(<"$stderr_file")"
}

test_authorized_renovate_pr_is_selected() {
  setup_case "authorized-renovate-pr"
  cat > "$MOCK_GRAPHQL_RESPONSE_FILE" <<'EOF'
{"data":{"repository":{"pullRequests":{"nodes":[{"number":17,"headRefOid":"deadbeef","author":{"login":"renovate[bot]"},"autoMergeRequest":{"enabledAt":"2026-08-06T18:00:00Z","enabledBy":{"login":"renovate[bot]"}}}]}}}}
EOF

  run_snippet "$FIND_PR_LOGIC"

  assert_eq "$RUN_STATUS" "0" "authorized find-pr status"
  assert_contains "$RUN_STDOUT" "Found eligible Renovate/Mergeraptor PR #17" "authorized find-pr output"
  assert_file_contains "$GITHUB_OUTPUT" "pr_number=17" "authorized find-pr output file"
  pass "authorized Renovate auto-merge request stays eligible"
}

test_manual_automerge_enablement_is_rejected() {
  setup_case "manual-automerge-enablement"
  cat > "$MOCK_GRAPHQL_RESPONSE_FILE" <<'EOF'
{"data":{"repository":{"pullRequests":{"nodes":[{"number":23,"headRefOid":"deadbeef","author":{"login":"app/mergeraptor"},"autoMergeRequest":{"enabledAt":"2026-08-06T18:00:00Z","enabledBy":{"login":"castrojo"}}}]}}}}
EOF

  run_snippet "$FIND_PR_LOGIC"

  assert_eq "$RUN_STATUS" "0" "manual enablement find-pr status"
  assert_contains "$RUN_STDOUT" "No eligible Renovate/Mergeraptor PR found" "manual enablement output"
  assert_file_contains "$GITHUB_OUTPUT" "pr_number=" "manual enablement output file"
  pass "manual or unauthorized auto-merge enablement is rejected"
}

run_non_pass_rollup_case() {
  local case_name="$1"
  local checks_json="$2"
  local checks_status="$3"
  local label="$4"

  setup_case "$case_name"
  printf '%s\n' "$checks_json" > "$MOCK_CHECKS_RESPONSE_FILE"
  export MOCK_CHECKS_EXIT_STATUS="$checks_status"

  run_snippet "$MERGE_LOGIC"

  assert_eq "$RUN_STATUS" "0" "${label} merge-step status"
  assert_contains "$RUN_STDOUT" "does not have a complete successful check rollup; skipping" "${label} merge-step output"
  assert_file_empty "$MOCK_MERGE_CALLS_FILE" "${label} unexpectedly attempted a merge"
  pass "${label} check rollup defers without merging"
}

test_successful_rollup_merges() {
  setup_case "successful-rollup"
  cat > "$MOCK_CHECKS_RESPONSE_FILE" <<'EOF'
[{"name":"Unit Tests","bucket":"pass"},{"name":"actionlint","bucket":"pass"}]
EOF

  run_snippet "$MERGE_LOGIC"

  assert_eq "$RUN_STATUS" "0" "successful merge-step status"
  assert_contains "$RUN_STDOUT" "Merged PR #101" "successful merge-step output"
  assert_file_contains "$MOCK_MERGE_CALLS_FILE" "pr merge 101 --squash --repo projectbluefin/actions" "successful merge command"
  pass "fully passing check rollup merges the PR"
}

test_authorized_renovate_pr_is_selected
test_manual_automerge_enablement_is_rejected
run_non_pass_rollup_case "empty-rollup" "[]" "0" "empty"
run_non_pass_rollup_case "failed-rollup" '[{"name":"Unit Tests","bucket":"fail"}]' "1" "failed"
run_non_pass_rollup_case "cancelled-rollup" '[{"name":"Unit Tests","bucket":"cancel"}]' "1" "cancelled"
run_non_pass_rollup_case "skipped-rollup" '[{"name":"Unit Tests","bucket":"skipping"}]' "1" "skipped"
run_non_pass_rollup_case "pending-rollup" '[{"name":"Unit Tests","bucket":"pending"}]' "8" "pending"
test_successful_rollup_merges
