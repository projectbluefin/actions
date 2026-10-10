#!/usr/bin/env bats
# Tests for the scan-image action's "Create CVE issue" step.
#
# The step body is read from bootc-build/scan-image/action.yml at test time,
# so these tests always exercise the shipped logic. `gh` is replaced by a stub
# on PATH that records every call and answers from fixture files.
#
# Covers:
#   - gh-token overrides github-token; github-token is the fallback
#   - only labels that exist in the repository are applied
#   - CVEs with an open issue are skipped; all-duplicate findings file nothing
#   - mixed findings: novel CVEs in the table, duplicates listed once
#   - placeholder rendering for missing package/installed/fixed fields
#   - gh failures (label list, issue search, issue create) warn, never fail

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCAN_ACTION="${REPO_ROOT}/bootc-build/scan-image/action.yml"

setup() {
  TEST_TMP=$(mktemp -d)
  export TEST_TMP

  export GITHUB_WORKSPACE="${TEST_TMP}/ws"
  mkdir -p "$GITHUB_WORKSPACE" "${TEST_TMP}/bin" "${TEST_TMP}/open"

  export GH_LOG="${TEST_TMP}/gh.log"
  export GH_TOKEN_LOG="${TEST_TMP}/gh-token.log"
  export GH_LABELS_JSON='[{"name":"priority/p0"},{"name":"area/security"},{"name":"kind/bug"}]'
  export GH_OPEN_DIR="${TEST_TMP}/open"
  export GH_CREATED_BODY="${TEST_TMP}/created-body.md"
  export GH_FAIL=""
  : > "$GH_LOG"
  : > "$GH_TOKEN_LOG"

  cat > "${TEST_TMP}/bin/gh" <<'STUB'
#!/usr/bin/env bash
# Records each invocation (one line, args joined by U+001F) and fakes replies.
printf '%s' "$1" >> "$GH_LOG"
shift_args=("$@")
for a in "${shift_args[@]:1}"; do printf '\x1f%s' "$a" >> "$GH_LOG"; done
printf '\n' >> "$GH_LOG"
printf '%s\n' "${GH_TOKEN:-}" >> "$GH_TOKEN_LOG"

case "$1 $2" in
  "label list")
    [[ "$GH_FAIL" == "label" ]] && { echo "label list boom" >&2; exit 1; }
    printf '%s\n' "$GH_LABELS_JSON"
    ;;
  "issue list")
    [[ "$GH_FAIL" == "search" ]] && { echo "search boom" >&2; exit 1; }
    search=""
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--search" ]]; then search="$2"; break; fi
      shift
    done
    cve="${search%% *}"
    if [[ -f "${GH_OPEN_DIR}/${cve}" ]]; then
      printf '[{"number":%s}]\n' "$(cat "${GH_OPEN_DIR}/${cve}")"
    else
      printf '[]\n'
    fi
    ;;
  "issue create")
    [[ "$GH_FAIL" == "create" ]] && { echo "create boom" >&2; exit 1; }
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--body-file" ]]; then cp "$2" "$GH_CREATED_BODY"; break; fi
      shift
    done
    echo "https://github.com/projectbluefin/test/issues/999"
    ;;
  *)
    echo "unexpected gh call: $*" >&2
    exit 2
    ;;
esac
STUB
  chmod +x "${TEST_TMP}/bin/gh"
  export PATH="${TEST_TMP}/bin:${PATH}"

  export GH_TOKEN_INPUT=""
  export GITHUB_TOKEN_INPUT="github-token-value"
  export ISSUE_TITLE="fix(security): critical CVE detected in testing build"
  export FINDINGS_FILE="${TEST_TMP}/findings.json"
  export REPO="projectbluefin/test"

  CREATE_ISSUE_LOGIC="$(create_issue_run_block)"
  export CREATE_ISSUE_LOGIC
}

teardown() {
  rm -rf "$TEST_TMP"
}

# Print the run block of the "Create CVE issue" step, as GitHub would run it.
create_issue_run_block() {
  python3 - "$SCAN_ACTION" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
steps = [s for s in doc["runs"]["steps"] if s.get("name") == "Create CVE issue"]
assert len(steps) == 1, f"expected one 'Create CVE issue' step, found {len(steps)}"
print(steps[0]["run"], end="")
PY
}

# write_findings <entries-json>
write_findings() {
  cat > "$FINDINGS_FILE" <<EOF
{
  "image": "localhost/test-image:latest",
  "repository": "projectbluefin/test",
  "ref_name": "testing",
  "scan_date": "2026-10-03",
  "run_url": "https://github.com/projectbluefin/test/actions/runs/12345",
  "critical_entries": $1
}
EOF
}

# mark_open <cve> <issue-number>
mark_open() {
  printf '%s' "$2" > "${GH_OPEN_DIR}/$1"
}

# Count gh invocations whose first two args match "<a> <b>".
gh_calls() {
  grep -c "^$1"$'\x1f'"$2" "$GH_LOG" || true
}

# Print the args of the single `gh issue create` call, one per line.
create_args() {
  grep "^issue"$'\x1f'"create" "$GH_LOG" | tr '\037' '\n'
}

ONE_CVE='[{"cve":"CVE-2026-0001","package":"openssl","installed":"3.0.1","fixed":"3.0.2"}]'

# ── Step extraction ──────────────────────────────────────────────────────────

@test "action.yml still ships exactly one 'Create CVE issue' step running gh" {
  [[ "$CREATE_ISSUE_LOGIC" == *'"gh", "issue", "create"'* ]]
  [[ "$CREATE_ISSUE_LOGIC" == *'desired_labels = ['* ]]
}

# ── Token selection ──────────────────────────────────────────────────────────

@test "token: empty gh-token falls back to github-token" {
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [ -s "$GH_TOKEN_LOG" ]
  run sort -u "$GH_TOKEN_LOG"
  [ "$output" = "github-token-value" ]
}

@test "token: non-empty gh-token overrides github-token for every gh call" {
  export GH_TOKEN_INPUT="override-token"
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  run sort -u "$GH_TOKEN_LOG"
  [ "$output" = "override-token" ]
}

# ── Issue creation ───────────────────────────────────────────────────────────

@test "create: novel CVE files one issue with title, repo and body file" {
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(gh_calls issue create)" -eq 1 ]

  run create_args
  [[ "$output" == *$'--repo\nprojectbluefin/test'* ]]
  [[ "$output" == *$'--title\nfix(security): critical CVE detected in testing build'* ]]
  [[ "$output" == *$'--body-file\n'"${GITHUB_WORKSPACE}/scan-image-issue-body.md"* ]]
}

@test "create: open-issue lookup searches each CVE among open issues only" {
  write_findings '[{"cve":"CVE-2026-0001","package":"a","installed":"1","fixed":"2"},{"cve":"CVE-2026-0002","package":"b","installed":"1","fixed":"2"}]'
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(gh_calls issue list)" -eq 2 ]
  grep -qF -- $'--state\x1fopen\x1f--search\x1fCVE-2026-0001 state:open' "$GH_LOG"
  grep -qF -- $'--state\x1fopen\x1f--search\x1fCVE-2026-0002 state:open' "$GH_LOG"
}

@test "create: body carries the scan metadata and one table row per CVE" {
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]

  body="$(cat "$GH_CREATED_BODY")"
  [[ "$body" == "## Critical CVEs detected by Trivy"* ]]
  [[ "$body" == *'- Image: `localhost/test-image:latest`'* ]]
  [[ "$body" == *'- Repository: `projectbluefin/test`'* ]]
  [[ "$body" == *'- Ref: `testing`'* ]]
  [[ "$body" == *'- Scan date (UTC): `2026-10-03`'* ]]
  [[ "$body" == *'- Workflow run: https://github.com/projectbluefin/test/actions/runs/12345'* ]]
  [[ "$body" == *'| CVE-2026-0001 | openssl | `3.0.1` | `3.0.2` |'* ]]
  [[ "$body" != *"Skipped because"* ]]
}

@test "create: missing package, installed and fixed fields render placeholders" {
  write_findings '[{"cve":"CVE-2026-0003","package":"","installed":"","fixed":""}]'
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  grep -qF '| CVE-2026-0003 | unknown | `unknown` | `none available` |' "$GH_CREATED_BODY"
}

# ── Labels ───────────────────────────────────────────────────────────────────

@test "labels: all three desired labels are applied when the repo has them" {
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  run create_args
  [[ "$output" == *$'--label\npriority/p0'* ]]
  [[ "$output" == *$'--label\narea/security'* ]]
  [[ "$output" == *$'--label\nkind/bug'* ]]
}

@test "labels: labels missing from the repo are dropped, not passed to gh" {
  export GH_LABELS_JSON='[{"name":"area/security"},{"name":"unrelated"}]'
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  run create_args
  [[ "$output" == *$'--label\narea/security'* ]]
  [[ "$output" != *"priority/p0"* ]]
  [[ "$output" != *"kind/bug"* ]]
  [[ "$output" != *"unrelated"* ]]
}

@test "labels: a repo with none of the labels still gets the issue, unlabelled" {
  export GH_LABELS_JSON='[]'
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(gh_calls issue create)" -eq 1 ]
  run create_args
  [[ "$output" != *"--label"* ]]
}

# ── De-duplication against open issues ───────────────────────────────────────

@test "dedupe: every CVE already tracked → notice, no issue created" {
  mark_open CVE-2026-0001 41
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::notice::Critical CVEs already have open issues; skipping auto-file"* ]]
  [ "$(gh_calls issue create)" -eq 0 ]
  [ ! -e "${GITHUB_WORKSPACE}/scan-image-issue-body.md" ]
}

@test "dedupe: mixed findings file only novel CVEs and list duplicates once" {
  mark_open CVE-2026-0001 41
  write_findings '[
    {"cve":"CVE-2026-0001","package":"openssl","installed":"3.0.1","fixed":"3.0.2"},
    {"cve":"CVE-2026-0002","package":"glibc","installed":"2.40","fixed":"2.41"},
    {"cve":"CVE-2026-0001","package":"openssl-libs","installed":"3.0.1","fixed":"3.0.2"}
  ]'
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(gh_calls issue create)" -eq 1 ]

  body="$(cat "$GH_CREATED_BODY")"
  [[ "$body" == *'| CVE-2026-0002 | glibc | `2.40` | `2.41` |'* ]]
  [[ "$body" != *"| CVE-2026-0001 |"* ]]
  [[ "$body" == *"Skipped because an open issue already exists for:"* ]]
  [ "$(grep -c '`CVE-2026-0001`' "$GH_CREATED_BODY")" -eq 1 ]
  run grep -F '`CVE-2026-0001`' "$GH_CREATED_BODY"
  [ "$output" = '`CVE-2026-0001`' ]
}

@test "dedupe: empty critical_entries files nothing" {
  write_findings '[]'
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipping auto-file"* ]]
  [ "$(gh_calls issue create)" -eq 0 ]
}

# ── gh failures never fail the build ─────────────────────────────────────────

@test "failure: gh label list error warns and exits 0 without creating" {
  export GH_FAIL="label"
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::warning::Failed to create CVE issue for projectbluefin/test"* ]]
  [ "$(gh_calls issue create)" -eq 0 ]
}

@test "failure: gh issue search error warns and exits 0 without creating" {
  export GH_FAIL="search"
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::warning::Failed to create CVE issue for projectbluefin/test"* ]]
  [ "$(gh_calls issue create)" -eq 0 ]
}

@test "failure: gh issue create error warns and exits 0" {
  export GH_FAIL="create"
  write_findings "$ONE_CVE"
  run bash -c "$CREATE_ISSUE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::warning::Failed to create CVE issue for projectbluefin/test"* ]]
}
