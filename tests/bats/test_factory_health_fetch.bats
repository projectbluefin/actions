#!/usr/bin/env bats
# Tests for the run fetch in .github/workflows/factory-health.yml (the
# `monitor_pipeline` shell function).
#
# The shell logic lives inline in the workflow YAML. The executable lines are
# captured here verbatim (FETCH_LOGIC) so any edit that changes testable
# behavior must also update this file. The rationale comments that sit between
# those lines in the workflow are deliberately not reproduced here: they
# document why the code is shaped this way, not what it does.
#
# The fetch is bounded by the monitoring window (`--created`) rather than by a
# run count (`--limit 100`). The regression guarded here is
# projectbluefin/actions#567: a count-bounded fetch samples "the N most recent
# runs, whatever their age or event", so on a busy repository the runs the job
# later discards evict production runs from the sample. Once discarded
# pre-merge runs have filled the sample, a healthy pipeline reads `no-runs`.
#
# The mock `gh` models the real API semantics, verified against gh 2.101.0 and
# the REST workflow-runs endpoint:
#   * `created` is applied *server-side* as a query parameter, so it decides
#     which runs are reachable as well as which are kept.
#   * `limit` is a page ceiling over that result — the newest N matching runs —
#     not a client-side filter applied after fetching.
# Both facts are what make the bug reproducible from a fixture: with
# `--limit 100` and no `--created`, runs older than the newest 100 are
# unreachable no matter what the caller filters afterwards.

# --- Verbatim excerpt from factory-health.yml ("Monitor 24h factory success
# --- rates" step): the window bound, the fetch, and the ceiling check. ---

FETCH_LOGIC=$(cat <<'EOF'
set -euo pipefail

WINDOW_HOURS=24
THRESHOLD=80
CUTOFF_EPOCH=$(date -u -d "${WINDOW_HOURS} hours ago" '+%s')
CUTOFF_ISO=$(date -u -d "@${CUTOFF_EPOCH}" '+%Y-%m-%dT%H:%M:%SZ')
FETCH_LIMIT=500

runs_json=$(gh run list \
  --repo "${repo}" \
  --workflow "${workflow}" \
  --created ">=${CUTOFF_ISO}" \
  --limit "${FETCH_LIMIT}" \
  --json createdAt,status,conclusion,url \
  2>/dev/null || echo '[]')

fetched=$(jq 'length' <<<"${runs_json}")
if (( fetched >= FETCH_LIMIT )); then
  echo "::warning::${repo} ${pipeline} (${workflow}) has ${fetched} runs in the ${WINDOW_HOURS}h window, at the ${FETCH_LIMIT}-run fetch ceiling; the success rate below is computed from a truncated sample."
fi

recent_json=$(jq --argjson cutoff "${CUTOFF_EPOCH}" '
  [ .[]
  | select((.createdAt | fromdateiso8601) >= $cutoff)
  ]
' <<<"${runs_json}")

jq 'length' <<<"${recent_json}"
EOF
)

setup() {
  TEST_TMP=$(mktemp -d)
  MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"
  export ARGS_FILE="${TEST_TMP}/gh-args"
  export GH_OUT="${TEST_TMP}/gh-out"

  # Workflow-level inputs, reproduced from factory-health.yml.
  export repo="projectbluefin/bluefin"
  export pipeline="Build"
  export workflow="Testing Images"

  # Default payload: one completed production run, in the window.
  export RUNS_JSON
  RUNS_JSON=$(jq -nc '[{createdAt: (now | todate), status: "completed",
    conclusion: "success", event: "push", url: "https://example.test/runs/1"}]')
  export GH_EXIT=0
  export GH_IGNORE_CREATED=""

  make_gh_mock
}

teardown() {
  rm -rf "$TEST_TMP"
}

# Mock `gh run list`. Records argv, then emulates the endpoint: `--created`
# selects by age, `--limit` caps at the newest N of the matches. Set
# GH_IGNORE_CREATED=1 to model a fetch that over-returns past the window, so
# the step's own window filter is what has to hold.
make_gh_mock() {
  cat > "${MOCK_DIR}/gh" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$ARGS_FILE"
if [ "${GH_EXIT:-0}" -ne 0 ]; then
  echo "mock gh failure" >&2
  exit "${GH_EXIT}"
fi

created=""
limit=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[i]}" in
    --created) created="${args[i + 1]}" ;;
    --limit) limit="${args[i + 1]}" ;;
  esac
done
[ -n "${GH_IGNORE_CREATED}" ] && created=""

payload=$(jq -c --arg created "$created" --argjson limit "${limit:-20}" '
  [ .[]
    | select($created == ""
             or ((.createdAt | fromdateiso8601)
                 >= ($created | ltrimstr(">=") | fromdateiso8601)))
  ][0:$limit]
' <<<"$RUNS_JSON")
printf '%s\n' "$payload" > "$GH_OUT"
printf '%s\n' "$payload"
MOCK
  chmod +x "${MOCK_DIR}/gh"
}

# Build $1 runs of event $2, all inside the window, newest first, with the
# newest $3 minutes ago and one minute between each.
runs_at_event() {
  local count="$1" event="$2" newest_minutes="$3"
  jq -nc --argjson n "${count}" --arg e "${event}" --argjson mins "${newest_minutes}" '
    [ range(0; $n)
      | {createdAt: (now - (($mins + .) * 60) | todate),
         status: "completed",
         conclusion: "success",
         event: $e,
         url: "https://example.test/runs/\(.)"}
    ]'
}

# The runs the mock actually returned, as a JSON array.
returned_runs() {
  jq -c '.' < "$GH_OUT"
}

# ── the fetch is bounded by the window, not by a run count ───────────────────

@test "fetch passes a --created bound matching the window filter's cutoff" {
  run bash -c "$FETCH_LOGIC"
  [ "$status" -eq 0 ]

  fetched_iso=$(sed -n 's/.*--created >=\([^ ]*\).*/\1/p' <<<"$(<"$ARGS_FILE")")
  [ -n "${fetched_iso}" ]
  expected_iso=$(date -u -d "@$(( $(date -u +%s) - 24 * 3600 ))" '+%Y-%m-%dT%H:%M:%SZ')
  # The snippet reads the clock itself, so allow a one-second skew.
  delta=$(( $(date -u -d "${fetched_iso}" +%s) - $(date -u -d "${expected_iso}" +%s) ))
  [ "${delta}" -le 1 ] && [ "${delta}" -ge -1 ]
}

@test "fetch ceiling is the generous bound, not the historical --limit 100" {
  run bash -c "$FETCH_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$(<"$ARGS_FILE")" == *'--limit 500'* ]]
  [[ "$(<"$ARGS_FILE")" != *'--limit 100'* ]]
}

@test "production runs behind 100 discarded pre-merge runs are still fetched" {
  # A PR-heavy workflow: 100 pre-merge runs sit on top of 20 production push
  # runs, all inside the window. Count-bounded, the newest 100 runs are every
  # one of them discarded — the pipeline reads no-runs while it is healthy.
  pr_runs=$(runs_at_event 100 "pull_request" 10)
  push_runs=$(runs_at_event 20 "push" 200)
  export RUNS_JSON
  RUNS_JSON=$(jq -nc --argjson pr "${pr_runs}" --argjson push "${push_runs}" '$pr + $push')

  run bash -c "$FETCH_LOGIC"
  [ "$status" -eq 0 ]

  # The window bound reaches past the discarded runs: all 120 are in the sample.
  [ "$output" = "120" ]
  # And the runs the job actually measures survived the fetch.
  [ "$(jq '[ .[] | select(.event == "push") ] | length' <<<"$(returned_runs)")" -eq 20 ]
}

@test "a count ceiling alone still loses those runs, so the time bound is the fix" {
  pr_runs=$(runs_at_event 100 "pull_request" 10)
  push_runs=$(runs_at_event 20 "push" 200)
  export RUNS_JSON
  RUNS_JSON=$(jq -nc --argjson pr "${pr_runs}" --argjson push "${push_runs}" '$pr + $push')

  # Same fetch, historical ceiling. The bound is in the query either way; a
  # bigger --limit only moves where truncation starts.
  run bash -c "${FETCH_LOGIC/FETCH_LIMIT=500/FETCH_LIMIT=100}"
  [ "$status" -eq 0 ]
  # The ceiling is hit, so the warning fires; the sample is still only 100.
  [ "$(tail -n1 <<<"$output")" = "100" ]
  [ "$(jq '[ .[] | select(.event == "push") ] | length' <<<"$(returned_runs)")" -eq 0 ]
}

# ── the ceiling is never silent ──────────────────────────────────────────────

@test "reaching the fetch ceiling warns that the sample is truncated" {
  RUNS_JSON=$(runs_at_event 500 "push" 10)
  export RUNS_JSON

  run bash -c "$FETCH_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::warning::${repo} ${pipeline} (${workflow})"* ]]
  [[ "$output" == *"500 runs in the 24h window"* ]]
  [[ "$output" == *"truncated sample"* ]]
}

@test "a sample under the ceiling warns about nothing" {
  RUNS_JSON=$(runs_at_event 499 "push" 10)
  export RUNS_JSON

  run bash -c "$FETCH_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" != *"::warning::"* ]]
}

# ── window integrity and the best-effort fetch contract ──────────────────────

@test "runs outside the window are excluded even when the fetch returns them" {
  in_window=$(runs_at_event 3 "push" 60)
  out_of_window=$(jq -nc '[{createdAt: (now - 25 * 3600 | todate), status: "completed",
    conclusion: "failure", event: "push", url: "https://example.test/runs/old"}]')
  export RUNS_JSON
  RUNS_JSON=$(jq -nc --argjson a "${in_window}" --argjson b "${out_of_window}" '$a + $b')
  export GH_IGNORE_CREATED=1

  run bash -c "$FETCH_LOGIC"
  [ "$status" -eq 0 ]
  [ "$output" = "3" ]
}

@test "a failed fetch stays non-fatal and yields an empty sample" {
  export GH_EXIT=1

  run bash -c "$FETCH_LOGIC"
  [ "$status" -eq 0 ]
  [ "$output" = "0" ]
}
