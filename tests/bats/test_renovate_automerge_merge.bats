#!/usr/bin/env bats
# Tests for the merge-step outcome reporting in
# .github/workflows/reusable-renovate-automerge.yml ("Merge PR" step).
#
# The shell logic lives inline in the workflow YAML. It is captured here
# verbatim (MERGE_LOGIC) so any edit to the step that changes testable
# behavior must also update this file.
#
# This addresses the auto-merge issue (#403): every production run has taken
# the skip path, so the merge step has never been executed against a real PR.
# In particular the issue flags that the outcome is reported by querying
# `gh pr view --json state` rather than trusting exit codes — correct in
# principle, but untested. These tests exercise the full merge/outcome path
# against mock `gh` outputs so a regression cannot silently change merge
# behaviour (or mis-report an enqueued PR) when a real qualifying PR lands.
#
# Covers:
#   - no strategy flag is passed for merge_method=queue
#   - a squash/merge/rebase strategy produces the matching --<method> flag
#   - an invalid merge_method is rejected with a ::error:: diagnostic
#   - a successful direct merge that reports MERGED says "Merged PR #N"
#   - a successful merge that reports OPEN says "Enqueued PR #N" (merge queue)
#   - an enqueued-by-earlier-attempt ("queued to merge") result is success
#   - a merge-queue rejection of an explicit-strategy merge is retried without
#     the strategy flag, and can then succeed
#   - a stable merge failure (unrelated error) exits non-zero
#   - the advisory/exit-code are never the basis of the report: the real PR
#     state is queried afterwards
#   - every merge attempt, including the strategy-less retry, is pinned to the
#     qualified commit with --match-head-commit "$HEAD_SHA" (#649), so a push
#     after the check-rollup gate can never be merged unreviewed
#   - a 409 (head moved after qualification) is a clean skip: exit 0, no retry,
#     no outcome report
#   - a moved head is also detected from the PR's current headRefOid, because
#     gh reports the --match-head-commit refusal as a GraphQL error on HTTP
#     200, not a 409 (#699); this applies to the strategy-less retry too
#   - an unchanged or unreadable head is not mistaken for a moved one

# --- Verbatim run block from reusable-renovate-automerge.yml (id: merge) ---
MERGE_LOGIC=$(cat <<'EOF'
set -euo pipefail
# --auto is intentionally never used:
#   1. an unprotected base branch rejects it entirely
#      (enablePullRequestAutoMerge → "Protected branch rules not configured")
#   2. it routes through GitHub's auto-merge queue, which does NOT
#      honour bypass_pull_request_allowances; only direct merges do.
# CI success is verified by the check-rollup gate above.
case "$MERGE_METHOD" in
  queue) flags=() ;;
  squash|merge|rebase) flags=("--$MERGE_METHOD") ;;
  *) echo "::error::merge_method must be squash, merge, rebase, or queue (got '$MERGE_METHOD')"; exit 1 ;;
esac

# `gh pr merge` writes advisories to stderr as "! ..." lines. Never
# infer the outcome from them or from the exit code: on a merge-queue
# branch an explicit strategy flag warns and still enqueues with exit
# 0, while a plain enqueue prints nothing at all. Ask for the real
# state afterwards instead.
report_outcome() {
  local state
  state=$(gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" \
    --json state --jq .state 2>/dev/null || echo "UNKNOWN")
  case "$state" in
    MERGED) echo "Merged PR #$PR_NUMBER" ;;
    OPEN)   echo "Enqueued PR #$PR_NUMBER (merge queue will land it shortly)" ;;
    *)      echo "PR #$PR_NUMBER accepted the merge; state is $state" ;;
  esac
}

if gh pr merge "$PR_NUMBER" "${flags[@]}" --match-head-commit "$HEAD_SHA" --repo "$GITHUB_REPOSITORY" 2>merge.err; then
  cat merge.err >&2
  report_outcome
  exit 0
fi

cat merge.err >&2

# A moved head is refused because of --match-head-commit. gh sends
# the pin as expectedHeadOid on the GraphQL mergePullRequest
# mutation, so the refusal arrives as a "GraphQL: ..." error on
# HTTP 200, not as an HTTP 409. Read the PR's current head instead
# of parsing the message. This is a normal, non-failing outcome
# (Renovate retries; a later workflow_run re-evaluates the PR), so
# log it and succeed rather than failing the job on a branch the
# gate never qualified. An unreadable head is not treated as moved.
head_moved() {
  local current
  current=$(gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" \
    --json headRefOid --jq .headRefOid 2>/dev/null || echo "")
  [ -n "$current" ] && [ "$current" != "$HEAD_SHA" ]
}
if grep -qi "409" merge.err || head_moved; then
  echo "PR #$PR_NUMBER head moved after qualification; merge skipped, Renovate will retry"
  exit 0
fi

# Already enqueued by an earlier attempt — that is success. Note this
# message does NOT contain the substring "merge queue".
if grep -qi "queued to merge" merge.err; then
  report_outcome
  exit 0
fi

# Defensive: current gh only warns, but a future version may hard-fail
# when a strategy flag is passed on a queued branch. Retry with none.
if [ "${#flags[@]}" -ne 0 ] && grep -qi "merge queue" merge.err; then
  echo "Base branch uses a merge queue; retrying without an explicit strategy"
  if gh pr merge "$PR_NUMBER" --match-head-commit "$HEAD_SHA" --repo "$GITHUB_REPOSITORY" 2>retry.err; then
    cat retry.err >&2
    report_outcome
    exit 0
  fi
  cat retry.err >&2
  if grep -qi "409" retry.err || head_moved; then
    echo "PR #$PR_NUMBER head moved after qualification; merge skipped, Renovate will retry"
    exit 0
  fi
  if grep -qi "queued to merge" retry.err; then
    report_outcome
    exit 0
  fi
  exit 1
fi

exit 1
EOF
)

setup() {
  TEST_TMP=$(mktemp -d)
  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"
  export SCRIPT_DIR="${TEST_TMP}/script"
  mkdir -p "$SCRIPT_DIR"
  export MERGE_CALL_FILE="${TEST_TMP}/merge_calls"
  echo 0 > "$MERGE_CALL_FILE"
  export VIEW_CALL_FILE="${TEST_TMP}/view_calls"
  echo 0 > "$VIEW_CALL_FILE"
  export HEAD_VIEW_CALL_FILE="${TEST_TMP}/head_view_calls"
  echo 0 > "$HEAD_VIEW_CALL_FILE"

  export PR_NUMBER=123
  export GITHUB_REPOSITORY="projectbluefin/test"
  export HEAD_SHA="0123456789abcdef0123456789abcdef01234567"
  export MERGE_ARGS_FILE="${TEST_TMP}/merge_args"
  : > "$MERGE_ARGS_FILE"

  # gh mock:
  #   gh pr merge  -> exit code and stderr are scripted per call via
  #                   ${SCRIPT_DIR}/merge_<N>.exit and merge_<N>.err
  #                   (default: exit 0, empty stderr). Each call's
  #                   arguments are appended to $MERGE_ARGS_FILE, one line
  #                   per call.
  #   gh pr view   -> with --json headRefOid: prints ${SCRIPT_DIR}/head_<N>
  #                   for head query N, else PR_HEAD_OID (default: the
  #                   qualified $HEAD_SHA, i.e. the head did not move),
  #                   or fails when PR_HEAD_OID_FAIL=1. These calls are
  #                   counted separately so they never shift view_<N>.
  #                   Otherwise prints the scripted state for view call N,
  #                   or PR_VIEW_STATE_DEFAULT if no per-call state is staged.
  cat > "${MOCK_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "pr merge")
    n=$(cat "$MERGE_CALL_FILE"); n=$((n + 1)); echo "$n" > "$MERGE_CALL_FILE"
    printf '%s\n' "$*" >> "$MERGE_ARGS_FILE"
    e="${SCRIPT_DIR}/merge_${n}.exit"; [ -f "$e" ] || e="${SCRIPT_DIR}/merge_default.exit"
    [ -f "$e" ] || echo 0 > "$e"
    err="${SCRIPT_DIR}/merge_${n}.err"; [ -f "$err" ] || err="${SCRIPT_DIR}/merge_default.err"
    if [ -f "$err" ]; then cat "$err" >&2; fi
    exit "$(cat "$e")"
    ;;
  "pr view")
    if [[ " $* " == *" headRefOid "* ]]; then
      n=$(cat "$HEAD_VIEW_CALL_FILE"); n=$((n + 1)); echo "$n" > "$HEAD_VIEW_CALL_FILE"
      [ "${PR_HEAD_OID_FAIL:-0}" = 1 ] && { echo "mock gh: HTTP 502" >&2; exit 1; }
      head="${SCRIPT_DIR}/head_${n}"; [ -f "$head" ] && { cat "$head"; exit 0; }
      printf '%s\n' "${PR_HEAD_OID:-$HEAD_SHA}"
      exit 0
    fi
    n=$(cat "$VIEW_CALL_FILE"); n=$((n + 1)); echo "$n" > "$VIEW_CALL_FILE"
    state="${SCRIPT_DIR}/view_${n}"; [ -f "$state" ] && { cat "$state"; exit 0; }
    printf '%s\n' "${PR_VIEW_STATE_DEFAULT:-MERGED}"
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

# Stage the exit code and stderr for a single `gh pr merge` invocation.
# Call 1 feeds merge.err; call 2 (the retry) feeds retry.err.
script_merge() {
  local n=$1 exit_code=$2 err=$3
  echo "$exit_code" > "${SCRIPT_DIR}/merge_${n}.exit"
  printf '%s\n' "$err" > "${SCRIPT_DIR}/merge_${n}.err"
}

# Stage the `gh pr view --json headRefOid` output for head query N.
script_head() {
  local n=$1 oid=$2
  printf '%s\n' "$oid" > "${SCRIPT_DIR}/head_${n}"
}

# Stage the `gh pr view --json state` output for a given report_outcome call.
script_view_state() {
  local n=$1 state=$2
  printf '%s\n' "$state" > "${SCRIPT_DIR}/view_${n}"
}

merge_calls() {
  cat "$MERGE_CALL_FILE"
}

# Arguments of the Nth `gh pr merge` call.
merge_args() {
  sed -n "${1}p" "$MERGE_ARGS_FILE"
}

view_calls() {
  cat "$VIEW_CALL_FILE"
}

head_view_calls() {
  cat "$HEAD_VIEW_CALL_FILE"
}

# Run the merge logic from an isolated dir: the step writes merge.err /
# retry.err to the working directory.
run_logic() {
  ( cd "$TEST_TMP" && bash -c "$MERGE_LOGIC" )
}

@test "invalid merge_method is rejected with a diagnostic" {
  export MERGE_METHOD=bogus
  run run_logic
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::merge_method must be squash, merge, rebase, or queue"* ]]
  [ "$(merge_calls)" = "0" ]
}

@test "queue method passes no strategy flag and reports a genuine MERGED state" {
  script_view_state 1 MERGED
  export MERGE_METHOD=queue
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "1" ]
  [[ "$output" == *"Merged PR #$PR_NUMBER"* ]]
  [[ "$output" != *"Enqueued PR"* ]]
}

@test "successful direct merge that actually enqueued reports OPEN state" {
  # gh pr merge exits 0 (queue branch accepts a strategy flag with a warning)
  # but the real PR state is OPEN -> must report "Enqueued PR", not MERGED.
  export MERGE_METHOD=squash
  script_view_state 1 OPEN
  run run_logic
  [ "$status" -eq 0 ]
  [[ "$output" == *"Enqueued PR #$PR_NUMBER"* ]]
}

@test "an earlier attempt already enqueued the PR is treated as success" {
  export MERGE_METHOD=merge
  script_merge 1 1 "! The PR is queued to merge"
  script_view_state 1 OPEN
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "1" ]
  [[ "$output" == *"Enqueued PR #$PR_NUMBER"* ]]
}

@test "merge-queue rejection of strategy flag retries and then reports success" {
  export MERGE_METHOD=squash
  script_merge 1 1 "Pull request #123 cannot be merged with an explicit strategy because the base branch uses a merge queue"
  script_merge 2 0 ""
  script_view_state 1 MERGED
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "2" ]
  [[ "$output" == *"retrying without an explicit strategy"* ]]
  [[ "$output" == *"Merged PR #$PR_NUMBER"* ]]
}

@test "retry that reports the PR was queued to merge is success" {
  export MERGE_METHOD=squash
  script_merge 1 1 "the base branch uses a merge queue"
  script_merge 2 1 "! The PR is queued to merge"
  script_view_state 1 OPEN
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "2" ]
  [[ "$output" == *"Enqueued PR #$PR_NUMBER"* ]]
}

@test "a stable non-queue merge failure exits non-zero" {
  export MERGE_METHOD=merge
  script_merge 1 1 "fatal: not authorized to merge pull request #123"
  run run_logic
  [ "$status" -ne 0 ]
  [ "$(merge_calls)" = "1" ]
  [[ "$output" == *"not authorized"* ]]
}

@test "report always reflects the queried state even when gh pr view is scripted" {
  # A successful merge whose post-query state is UNKNOWN (query failed) must
  # report the fallback rather than hardcoding "Merged".
  export MERGE_METHOD=squash
  script_merge 1 0 ""
  script_view_state 1 UNKNOWN
  run run_logic
  [ "$status" -eq 0 ]
  [[ "$output" == *"state is UNKNOWN"* ]]
}

@test "the merge is pinned to the qualified head commit" {
  export MERGE_METHOD=squash
  script_view_state 1 MERGED
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "1" ]
  [[ "$(merge_args 1)" == *"--squash"* ]]
  [[ "$(merge_args 1)" == *"--match-head-commit $HEAD_SHA"* ]]
}

@test "queue method still pins the head commit without a strategy flag" {
  export MERGE_METHOD=queue
  run run_logic
  [ "$status" -eq 0 ]
  [[ "$(merge_args 1)" == *"--match-head-commit $HEAD_SHA"* ]]
  [[ "$(merge_args 1)" != *"--squash"* ]]
  [[ "$(merge_args 1)" != *"--merge "* ]]
  [[ "$(merge_args 1)" != *"--rebase"* ]]
}

@test "the strategy-less merge-queue retry keeps the head-commit pin" {
  export MERGE_METHOD=rebase
  script_merge 1 1 "the base branch uses a merge queue"
  script_merge 2 0 ""
  script_view_state 1 OPEN
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "2" ]
  [[ "$(merge_args 1)" == *"--rebase"* ]]
  [[ "$(merge_args 2)" != *"--rebase"* ]]
  [[ "$(merge_args 2)" == *"--match-head-commit $HEAD_SHA"* ]]
}

@test "a 409 for a head that moved after qualification is a clean skip" {
  export MERGE_METHOD=squash
  script_merge 1 1 "HTTP 409: Head branch was modified. Review and try the merge again."
  run run_logic
  [ "$status" -eq 0 ]
  [[ "$output" == *"head moved after qualification; merge skipped"* ]]
  [ "$(merge_calls)" = "1" ]
  [ "$(view_calls)" = "0" ]
  [[ "$output" != *"Merged PR"* ]]
  [[ "$output" != *"Enqueued PR"* ]]
}

@test "a 409 that mentions the merge queue is still a skip, not a retry" {
  # The 409 check runs before the merge-queue retry: a moved head must never
  # be retried without the strategy flag.
  export MERGE_METHOD=squash
  script_merge 1 1 "HTTP 409: head moved; base branch uses a merge queue"
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "1" ]
  [[ "$output" == *"merge skipped"* ]]
  [[ "$output" != *"retrying without an explicit strategy"* ]]
}

# gh pr merge --match-head-commit sends expectedHeadOid on the GraphQL
# mergePullRequest mutation, so a moved head comes back as a GraphQL error on
# HTTP 200 with no "409" in it (#699). The PR's current head decides instead.
MOVED_HEAD="fedcba9876543210fedcba9876543210fedcba98"

@test "a GraphQL refusal with a moved head is a clean skip" {
  export MERGE_METHOD=squash
  export PR_HEAD_OID="$MOVED_HEAD"
  script_merge 1 1 "GraphQL: Head branch was modified. Review and try the merge again. (mergePullRequest)"
  run run_logic
  [ "$status" -eq 0 ]
  [[ "$output" == *"head moved after qualification; merge skipped"* ]]
  [ "$(merge_calls)" = "1" ]
  [ "$(head_view_calls)" = "1" ]
  [ "$(view_calls)" = "0" ]
  [[ "$output" != *"Merged PR"* ]]
}

@test "a moved head is a skip even when the error mentions the merge queue" {
  # The head check runs before the merge-queue retry: a moved head must never
  # be retried without the strategy flag.
  export MERGE_METHOD=squash
  export PR_HEAD_OID="$MOVED_HEAD"
  script_merge 1 1 "GraphQL: head moved; base branch uses a merge queue (mergePullRequest)"
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "1" ]
  [[ "$output" == *"merge skipped"* ]]
  [[ "$output" != *"retrying without an explicit strategy"* ]]
}

@test "a strategy-less retry refused because the head moved is a clean skip" {
  export MERGE_METHOD=squash
  script_merge 1 1 "the base branch uses a merge queue"
  script_merge 2 1 "GraphQL: Head branch was modified. Review and try the merge again. (mergePullRequest)"
  # First head check (after the first attempt) sees the qualified commit; the
  # push lands between the two attempts.
  script_head 1 "$HEAD_SHA"
  script_head 2 "$MOVED_HEAD"
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "2" ]
  [ "$(head_view_calls)" = "2" ]
  [[ "$output" == *"retrying without an explicit strategy"* ]]
  [[ "$output" == *"head moved after qualification; merge skipped"* ]]
}

@test "a 409 on the strategy-less retry is a clean skip" {
  export MERGE_METHOD=squash
  script_merge 1 1 "the base branch uses a merge queue"
  script_merge 2 1 "HTTP 409: Head branch was modified."
  run run_logic
  [ "$status" -eq 0 ]
  [ "$(merge_calls)" = "2" ]
  [[ "$output" == *"merge skipped"* ]]
}

@test "an unrelated failure with an unchanged head still fails" {
  export MERGE_METHOD=merge
  export PR_HEAD_OID="$HEAD_SHA"
  script_merge 1 1 "GraphQL: Resource not accessible by integration (mergePullRequest)"
  run run_logic
  [ "$status" -eq 1 ]
  [ "$(head_view_calls)" = "1" ]
  [[ "$output" != *"merge skipped"* ]]
}

@test "an unreadable head is not mistaken for a moved one" {
  export MERGE_METHOD=merge
  export PR_HEAD_OID_FAIL=1
  script_merge 1 1 "GraphQL: Resource not accessible by integration (mergePullRequest)"
  run run_logic
  [ "$status" -eq 1 ]
  [ "$(head_view_calls)" = "1" ]
  [[ "$output" != *"merge skipped"* ]]
}
