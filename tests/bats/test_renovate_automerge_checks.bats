#!/usr/bin/env bats
# Tests for the check-rollup classification in
# .github/workflows/reusable-renovate-automerge.yml ("Require a complete,
# all-successful check rollup" step).
#
# The shell logic lives inline in the workflow YAML. It is captured here
# verbatim (CHECKS_LOGIC) so any edit to the step that changes testable
# behavior must also update this file.
#
# Covers:
#   - All-successful rollup with no in-flight runs -> ready=true
#   - QUEUED checks are awaited, then ready once they succeed (regression:
#     nonterminal check states were classified as blockers, so the step
#     gave up immediately instead of waiting out check_timeout_seconds)
#   - Every nonterminal state (PENDING QUEUED IN_PROGRESS WAITING REQUESTED
#     EXPECTED) is awaited, never reported as "non-passing"
#   - Every documented terminal failure state (FAILURE CANCELLED TIMED_OUT
#     ACTION_REQUIRED STARTUP_FAILURE STALE ERROR) blocks immediately
#   - Unrecognized states fail closed (blocked)
#   - In-flight workflow runs keep an all-success rollup waiting
#   - An unreadable run list is treated as still-settling, never as idle
#   - An empty rollup keeps waiting instead of merging

# --- Verbatim run block from reusable-renovate-automerge.yml (id: checks) ---

CHECKS_LOGIC=$(cat <<'EOF'
set -euo pipefail

# `gh pr checks --json state` reports a check-run's *status* while it
# is unfinished and its *conclusion* once COMPLETED; legacy status
# contexts report their raw state. Every nonterminal state — gh's own
# "pending" bucket: PENDING, QUEUED, IN_PROGRESS, WAITING, REQUESTED,
# EXPECTED — is awaited below, never treated as a failure.
# SKIPPED/NEUTRAL are non-blocking under GitHub's own merge semantics.
# Anything else — terminal failure conclusions (FAILURE, CANCELLED,
# TIMED_OUT, ACTION_REQUIRED, STARTUP_FAILURE, STALE, ERROR) or an
# unrecognized state — blocks outright.
nonterminal='["PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "EXPECTED"]'
#
# An *absent* check is not a passing check. `gh pr checks` reports only
# the check-runs that currently exist, so a workflow that is queued but
# has not yet registered one is simply missing from the rollup rather
# than PENDING — and a re-run temporarily removes its check-runs
# entirely. Because this workflow is triggered by one CI workflow
# completing while siblings may still be queued, that race is the
# normal case. Cross-check in-flight workflow runs for the same commit
# so "no news" is never mistaken for good news.
deadline=$(( SECONDS + CHECK_TIMEOUT_SECONDS ))
ready=false

while :; do
  checks=$(gh pr checks "$PR_NUMBER" \
    --repo "$GITHUB_REPOSITORY" \
    --json name,state 2>/dev/null || true)
  [ -n "$checks" ] || checks='[]'

  succeeded=$(jq '[.[] | select(.state == "SUCCESS")] | length' <<<"$checks")
  pending=$(jq --argjson nt "$nonterminal" '[.[] | select(.state as $s | $nt | index($s) != null)] | length' <<<"$checks")
  blocked=$(jq --argjson nt "$nonterminal" '[.[] | select(.state != "SUCCESS" and .state != "SKIPPED" and .state != "NEUTRAL" and (.state as $s | $nt | index($s) == null))] | length' <<<"$checks")

  # Queued or running workflow runs for this exact commit, including
  # any that have not yet surfaced a check-run on the PR.
  inflight=$(gh run list \
    --repo "$GITHUB_REPOSITORY" \
    --commit "$HEAD_SHA" \
    --limit 100 \
    --json status \
    --jq '[.[] | select(.status != "completed")] | length' 2>/dev/null || echo "unknown")

  if [ "$blocked" -ne 0 ]; then
    jq -r --argjson nt "$nonterminal" '.[] | select(.state != "SUCCESS" and .state != "SKIPPED" and .state != "NEUTRAL" and (.state as $s | $nt | index($s) == null)) | "  \(.state)\t\(.name)"' <<<"$checks"
    echo "PR #$PR_NUMBER has $blocked non-passing check(s) — not merging"
    break
  fi

  # Treat an unreadable run list as still-settling rather than idle;
  # a transient API error must not be read as "nothing is running".
  if [ "$inflight" = "unknown" ]; then
    waiting=1
    reason="workflow run list unavailable"
  elif [ "$pending" -ne 0 ] || [ "$inflight" -ne 0 ]; then
    waiting=1
    reason="$pending pending check(s), $inflight in-flight run(s)"
  elif [ "$succeeded" -eq 0 ]; then
    # No checks at all yet: keep waiting rather than giving up, since
    # the rollup may simply not have been populated for this commit.
    waiting=1
    reason="no checks reported yet"
  else
    waiting=0
  fi

  if [ "$waiting" -eq 0 ]; then
    echo "All $succeeded checks succeeded for PR #$PR_NUMBER and no runs are in flight"
    ready=true
    break
  fi

  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "Timed out after ${CHECK_TIMEOUT_SECONDS}s — $reason; not merging"
    break
  fi

  echo "PR #$PR_NUMBER not settled ($reason); re-checking in 30s"
  sleep 30
done

# A non-ready result is deliberately not a job failure: Renovate will
# retry, and a later successful workflow_run re-evaluates the PR.
echo "ready=$ready" >> "$GITHUB_OUTPUT"
EOF
)

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"
  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  export PR_NUMBER=123
  export HEAD_SHA="0123456789abcdef0123456789abcdef"
  export GITHUB_REPOSITORY="projectbluefin/test"
  # Default: settle decisions instantly. Tests that exercise the wait loop
  # override this; sleep is mocked to a no-op either way.
  export CHECK_TIMEOUT_SECONDS=0

  export CHECKS_JSON="${TEST_TMP}/checks.json"
  printf '[]\n' > "$CHECKS_JSON"
  export RUN_LIST_RESPONSE=0
  export RUN_LIST_FAILS=0
  export CALL_COUNT_FILE="${TEST_TMP}/gh_pr_checks_calls"

  # gh mock: `gh pr checks` emits the staged JSON rollup (or the next file in
  # CHECKS_SEQ_DIR for multi-poll scenarios); `gh run list` emits the staged
  # count of in-flight runs (already --jq-filtered, as the real CLI would).
  cat > "${MOCK_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "pr checks")
    if [ -n "${CHECKS_SEQ_DIR:-}" ]; then
      n=$(cat "$CALL_COUNT_FILE" 2>/dev/null || echo 0)
      n=$((n + 1))
      echo "$n" > "$CALL_COUNT_FILE"
      f="${CHECKS_SEQ_DIR}/${n}.json"
      [ -f "$f" ] || f="${CHECKS_SEQ_DIR}/last.json"
      cat "$f"
    else
      cat "$CHECKS_JSON"
    fi
    ;;
  "run list")
    if [ "${RUN_LIST_FAILS:-0}" = "1" ]; then
      exit 1
    fi
    printf '%s\n' "$RUN_LIST_RESPONSE"
    ;;
  *)
    echo "mock gh: unexpected invocation: $*" >&2
    exit 1
    ;;
esac
EOF
  chmod +x "${MOCK_DIR}/gh"

  cat > "${MOCK_DIR}/sleep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "${MOCK_DIR}/sleep"
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | head -1 | cut -d= -f2-
}

checks_array() {
  local json='[]' i=0 s
  for s in "$@"; do
    i=$((i + 1))
    json=$(jq --arg n "check-$i" --arg s "$s" '. + [{name: $n, state: $s}]' <<<"$json")
  done
  printf '%s\n' "$json"
}

# Stage a fixed rollup returned by every `gh pr checks` call.
write_checks() {
  checks_array "$@" > "$CHECKS_JSON"
}

# Stage a per-poll rollup sequence, e.g. write_checks_sequence "QUEUED" "SUCCESS".
# Calls beyond the sequence replay the last entry.
write_checks_sequence() {
  CHECKS_SEQ_DIR="${TEST_TMP}/seq"
  mkdir -p "$CHECKS_SEQ_DIR"
  local n=0 call
  for call in "$@"; do
    n=$((n + 1))
    # shellcheck disable=SC2086
    checks_array $(tr ',' ' ' <<<"$call") > "${CHECKS_SEQ_DIR}/${n}.json"
  done
  cp "${CHECKS_SEQ_DIR}/${n}.json" "${CHECKS_SEQ_DIR}/last.json"
  export CHECKS_SEQ_DIR
}

@test "all-successful rollup with no in-flight runs is ready" {
  write_checks SUCCESS SKIPPED NEUTRAL
  run bash -c "$CHECKS_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"All 1 checks succeeded"* ]]
  [ "$(get_output ready)" = "true" ]
}

@test "queued checks are awaited, then ready once they succeed" {
  export CHECK_TIMEOUT_SECONDS=900
  write_checks_sequence "SUCCESS,QUEUED,QUEUED" "SUCCESS,SUCCESS,SUCCESS"
  run bash -c "$CHECKS_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"not settled (2 pending check(s), 0 in-flight run(s))"* ]]
  [[ "$output" != *"non-passing check(s)"* ]]
  [[ "$output" == *"All 3 checks succeeded"* ]]
  [ "$(get_output ready)" = "true" ]
}

@test "nonterminal check states are awaited, not blocked" {
  for state in PENDING QUEUED IN_PROGRESS WAITING REQUESTED EXPECTED; do
    : > "$GITHUB_OUTPUT"
    write_checks SUCCESS "$state"
    run bash -c "$CHECKS_LOGIC"
    [ "$status" -eq 0 ]
    if [[ "$output" == *"non-passing check(s)"* ]]; then
      echo "$state was classified as a blocker"
      return 1
    fi
    [[ "$output" == *"1 pending check(s), 0 in-flight run(s)"* ]]
    [[ "$output" == *"Timed out after 0s"* ]]
    [ "$(get_output ready)" = "false" ]
  done
}

@test "terminal failure states block immediately" {
  export CHECK_TIMEOUT_SECONDS=900
  for state in FAILURE CANCELLED TIMED_OUT ACTION_REQUIRED STARTUP_FAILURE STALE ERROR; do
    : > "$GITHUB_OUTPUT"
    write_checks SUCCESS "$state"
    run bash -c "$CHECKS_LOGIC"
    [ "$status" -eq 0 ]
    [[ "$output" == *"check-2"* ]]
    [[ "$output" == *"has 1 non-passing check(s) — not merging"* ]]
    [ "$(get_output ready)" = "false" ]
  done
}

@test "unrecognized check states fail closed" {
  write_checks SUCCESS BIZARRE
  run bash -c "$CHECKS_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"has 1 non-passing check(s) — not merging"* ]]
  [ "$(get_output ready)" = "false" ]
}

@test "in-flight workflow runs keep an all-success rollup waiting" {
  export RUN_LIST_RESPONSE=1
  write_checks SUCCESS
  run bash -c "$CHECKS_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"0 pending check(s), 1 in-flight run(s)"* ]]
  [[ "$output" == *"Timed out after 0s"* ]]
  [ "$(get_output ready)" = "false" ]
}

@test "unreadable workflow run list is treated as still-settling" {
  export RUN_LIST_FAILS=1
  write_checks SUCCESS
  run bash -c "$CHECKS_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"workflow run list unavailable"* ]]
  [ "$(get_output ready)" = "false" ]
}

@test "empty rollup keeps waiting instead of merging" {
  write_checks
  run bash -c "$CHECKS_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"no checks reported yet"* ]]
  [ "$(get_output ready)" = "false" ]
}
