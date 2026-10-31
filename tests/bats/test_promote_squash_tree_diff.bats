#!/usr/bin/env bats
# Tests for the "Collect tree diff for PR body" step (id: treediff) in
# .github/workflows/reusable-promote-squash.yml.
#
# Regression coverage for #691: on a squash-only target branch the source
# shares no history with what was already promoted, so a commit count reported
# every commit since the branches forked while the real delta was tiny. The
# step must report the tree difference against the current target tip.

setup() {
  TEST_TMP="$(mktemp -d)"
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"
  export SOURCE_BRANCH="main"
  export TARGET_BRANCH="stable"
  export PROMOTION_BRANCH="auto/promote-main-to-stable"

  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com
  export GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com

  # Squash-only history: stable receives one squash commit per promotion and
  # never shares main's commits. main then gets one more small change.
  git init -q -b main "${TEST_TMP}/repo"
  cd "${TEST_TMP}/repo" || return 1
  echo base > README
  git add README && git commit -qm base
  git checkout -qb stable
  git checkout -q main
  for i in $(seq 1 30); do
    echo "line $i" >> notes.txt
    git add notes.txt && git commit -qm "feat: change $i"
  done
  git checkout -q stable
  git checkout -q main -- .
  git commit -qm "chore: promote main to stable"
  git checkout -q main
  echo "digest: sha256:new" > image-versions.yml
  printf 'bin\0ary' > logo.bin
  git add image-versions.yml logo.bin && git commit -qm "chore(deps): bump digest"
  # The workflow diffs remote-tracking refs.
  git update-ref refs/remotes/origin/main main
  git update-ref refs/remotes/origin/stable stable
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

load_treediff_logic() {
  local workflow_file="${BATS_TEST_DIRNAME}/../../.github/workflows/reusable-promote-squash.yml"
  python3 -c "
import yaml
with open('${workflow_file}') as f:
    wf = yaml.safe_load(f)
step = next(s for s in wf['jobs']['promote']['steps'] if s.get('id') == 'treediff')
print(step['run'].replace('\${{ github.repository }}', 'projectbluefin/finpilot'))
"
}

@test "squash-only history: reports the tree diff, not the commit distance" {
  # Sanity: the old metric is inflated by already-promoted commits.
  [ "$(git rev-list --count origin/stable..origin/main)" -eq 31 ]

  run bash -c "$(load_treediff_logic)"
  [ "$status" -eq 0 ]

  DIFF_JSON=$(get_output diff_json)
  [ "$(jq -r .files_changed <<<"$DIFF_JSON")" -eq 2 ]
  [ "$(jq -r .insertions <<<"$DIFF_JSON")" -eq 1 ]
  [ "$(jq -r .deletions <<<"$DIFF_JSON")" -eq 0 ]
  [ "$(jq -r '[.files[].path] | sort | join(",")' <<<"$DIFF_JSON")" = "image-versions.yml,logo.bin" ]
  [ "$(jq -r '.files[] | select(.path == "logo.bin") | .insertions' <<<"$DIFF_JSON")" = "null" ]
}

@test "compare URL points at the squash branch, not the source branch" {
  run bash -c "$(load_treediff_logic)"
  [ "$status" -eq 0 ]
  [ "$(get_output compare_url)" = "https://github.com/projectbluefin/finpilot/compare/stable...auto/promote-main-to-stable" ]
}

@test "file list is capped at 50 while files_changed keeps the total" {
  for i in $(seq 1 60); do echo "$i" > "gen_$i.txt"; done
  git add . && git commit -qm "many files"
  git update-ref refs/remotes/origin/main main

  run bash -c "$(load_treediff_logic)"
  [ "$status" -eq 0 ]
  DIFF_JSON=$(get_output diff_json)
  [ "$(jq -r .files_changed <<<"$DIFF_JSON")" -eq 62 ]
  [ "$(jq -r '.files | length' <<<"$DIFF_JSON")" -eq 50 ]
}
