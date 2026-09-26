#!/usr/bin/env bats
# Tests for the pipeline status classification in
# .github/workflows/factory-health.yml (monitor_pipeline step).
#
# The shell logic lives inline in the workflow YAML. It is captured here
# verbatim (CLASSIFY_LOGIC) so any edit to the step that changes testable
# behavior must also update this file. scripts/monitor_pipeline.py mirrors
# the same rules in Python; tests/test_monitor_pipeline.py covers that copy.
#
# Keeping the two copies in lockstep is enforced, not merely asked for:
# tests/test_factory_health_classify_sync.py parses the workflow and fails if
# the block between the verbatim markers below drifts from it, or if the
# thresholds exported in setup() stop matching the workflow's. That test runs
# under pytest, which unit-tests.yml triggers on factory-health.yml edits, so
# a workflow-only change cannot pass green with this file left stale. The
# markers are part of the contract — move them with the block, don't delete
# them to make the check pass.
#
# Regression coverage for projectbluefin/actions#479:
# "Nightly E2E" runs once a day, so a 24h window holds exactly one completed
# run and the only rates it can report are 100% and 0%. One flaky night put
# the pipeline at 0/1 and filed a priority/p0 issue. Below MIN_RUNS the rate
# is not trusted and the status is "low-sample" — but a pipeline that fails
# MIN_CONSECUTIVE_FAILURES times back-to-back still alerts, so the sample
# floor never becomes a blind spot.

CLASSIFY_LOGIC=$(cat <<'EOF'
set -euo pipefail

# --- verbatim from factory-health.yml, monitor_pipeline() ---
recent_json=$(jq --argjson cutoff "${CUTOFF_EPOCH}" '
  [ .[]
  | select((.createdAt | fromdateiso8601) >= $cutoff)
  ]
' <<<"${runs_json}")

completed_json=$(jq '
  [ .[]
  # Only genuine build outcomes count toward the success rate.
  # Cancelled runs were preempted (not failed) and action_required
  # runs are pending approval — neither produced a build result, so
  # counting them deflates the rate and fires false alerts
  # (projectbluefin/actions#483). skipped/in_progress excluded too.
  #
  # Pre-merge validation events (pull_request, merge_group) reflect
  # in-flight work, not the deployed pipeline. A failed PR run or a
  # merge-queue collision routinely gets fixed and re-run before the
  # branch lands, so counting them as "Build" failures produces false
  # alerts (projectbluefin/actions#503). Only production pipeline
  # events (push, schedule, workflow_dispatch, workflow_run, etc.)
  # measure real pipeline health.
  | select(.status == "completed" and (.conclusion == "success" or .conclusion == "failure"))
  | select(.event != "pull_request" and .event != "merge_group")
  ]
' <<<"${recent_json}")

total=$(jq 'length' <<<"${completed_json}")
success=$(jq '[ .[] | select(.conclusion == "success") ] | length' <<<"${completed_json}")

# Back-to-back failures on the most recent completed runs, read from
# the whole fetched history rather than the window: a once-a-day
# pipeline has one run in a 24h window, so the window alone cannot
# tell a one-off flake from a pipeline failing every night.
# index("success") is the count of leading failures; null (never
# succeeded in the fetched history) falls back to the run count.
consecutive_failures=$(jq '
  [ .[]
  | select(.status == "completed" and (.conclusion == "success" or .conclusion == "failure"))
  ]
  | sort_by(.createdAt)
  | reverse
  | map(.conclusion)
  | (index("success") // length)
' <<<"${runs_json}")

if (( total > 0 )); then
  rate_value=$(( success * 100 / total ))
  rate_display="${rate_value}%"
  if (( rate_value >= THRESHOLD )); then
    status="healthy"
  elif (( total >= MIN_RUNS )); then
    status="alert"
  elif (( consecutive_failures >= MIN_CONSECUTIVE_FAILURES )); then
    # Under-sampled, but failing run after run — a real outage.
    status="alert"
  else
    status="low-sample"
  fi
else
  rate_value=-1
  rate_display="n/a"
  status="no-runs"
fi
# --- end verbatim ---

echo "status=${status}"
echo "total=${total}"
echo "rate=${rate_display}"
echo "consecutive_failures=${consecutive_failures}"
EOF
)

setup() {
  export THRESHOLD=80
  export MIN_RUNS=3
  export MIN_CONSECUTIVE_FAILURES=2
  export CUTOFF_EPOCH
  CUTOFF_EPOCH=$(date -u -d '24 hours ago' '+%s')
}

# Build one run object N hours in the past.
run_obj() {
  local conclusion="$1" hours_ago="$2" status="${3:-completed}"
  local created
  created=$(date -u -d "${hours_ago} hours ago" '+%Y-%m-%dT%H:%M:%SZ')
  jq -n \
    --arg conclusion "$conclusion" \
    --arg createdAt "$created" \
    --arg status "$status" \
    '{createdAt: $createdAt, status: $status, conclusion: $conclusion,
      url: "https://github.com/org/repo/actions/runs/1"}'
}

runs() {
  printf '%s\n' "$@" | jq -s '.'
}

classify() {
  runs_json="$1" bash -c "$CLASSIFY_LOGIC"
}

@test "a single failed run in the window is low-sample, not an alert" {
  # The #479 shape: Nightly E2E, 0/1, nothing before it.
  run classify "$(runs "$(run_obj failure 2)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status=low-sample"* ]]
  [[ "$output" == *"total=1"* ]]
  [[ "$output" == *"rate=0%"* ]]
}

@test "two back-to-back failures escalate an under-sampled pipeline to alert" {
  # One failure inside the window, one the night before — a real outage.
  run classify "$(runs "$(run_obj failure 2)" "$(run_obj failure 26)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status=alert"* ]]
  [[ "$output" == *"total=1"* ]]
  [[ "$output" == *"consecutive_failures=2"* ]]
}

@test "a recent success breaks the failure streak and keeps it low-sample" {
  run classify "$(runs \
    "$(run_obj failure 2)" \
    "$(run_obj success 26)" \
    "$(run_obj failure 50)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status=low-sample"* ]]
  [[ "$output" == *"consecutive_failures=1"* ]]
}

@test "a sample at the floor still alerts below the threshold" {
  run classify "$(runs \
    "$(run_obj failure 2)" \
    "$(run_obj failure 4)" \
    "$(run_obj success 6)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status=alert"* ]]
  [[ "$output" == *"total=3"* ]]
}

@test "the floor never suppresses a healthy single-run pipeline" {
  run classify "$(runs "$(run_obj success 2)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status=healthy"* ]]
  [[ "$output" == *"rate=100%"* ]]
}

@test "exactly at the threshold is healthy" {
  run classify "$(runs \
    "$(run_obj success 2)" \
    "$(run_obj success 3)" \
    "$(run_obj success 4)" \
    "$(run_obj success 5)" \
    "$(run_obj failure 6)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status=healthy"* ]]
  [[ "$output" == *"rate=80%"* ]]
}

@test "an empty window reports no-runs, not low-sample" {
  run classify "$(runs "$(run_obj failure 40)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status=no-runs"* ]]
  [[ "$output" == *"rate=n/a"* ]]
}

@test "no runs at all reports no-runs with a zero failure streak" {
  run classify '[]'
  [ "$status" -eq 0 ]
  [[ "$output" == *"status=no-runs"* ]]
  [[ "$output" == *"consecutive_failures=0"* ]]
}

@test "cancelled and in-progress runs neither count nor break the streak" {
  run classify "$(runs \
    "$(run_obj failure 2)" \
    "$(run_obj cancelled 3)" \
    "$(run_obj '' 4 in_progress)" \
    "$(run_obj failure 26)" \
    "$(run_obj success 50)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"total=1"* ]]
  [[ "$output" == *"consecutive_failures=2"* ]]
  [[ "$output" == *"status=alert"* ]]
}

@test "a history that never succeeded counts every fetched run as consecutive" {
  run classify "$(runs \
    "$(run_obj failure 2)" \
    "$(run_obj failure 26)" \
    "$(run_obj failure 50)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"consecutive_failures=3"* ]]
  [[ "$output" == *"status=alert"* ]]
}

@test "the streak is derived from timestamps, not input list order" {
  # Oldest-first input must classify the same as newest-first.
  run classify "$(runs \
    "$(run_obj success 50)" \
    "$(run_obj failure 26)" \
    "$(run_obj failure 2)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"consecutive_failures=2"* ]]
}

@test "a high-volume pipeline below the threshold alerts as before" {
  run classify "$(runs \
    "$(run_obj failure 1)" \
    "$(run_obj failure 2)" \
    "$(run_obj failure 3)" \
    "$(run_obj failure 4)" \
    "$(run_obj success 5)" \
    "$(run_obj success 6)" \
    "$(run_obj success 7)" \
    "$(run_obj success 8)" \
    "$(run_obj success 9)" \
    "$(run_obj success 10)")"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status=alert"* ]]
  [[ "$output" == *"rate=60%"* ]]
}
