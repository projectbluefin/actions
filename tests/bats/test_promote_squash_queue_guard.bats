#!/usr/bin/env bats
# Tests for queue-entry guard in .github/workflows/reusable-promote-squash.yml (rebuild step).
#
# Regression coverage for GH006:
# When an existing promotion PR is already queued in the GitHub merge queue (mergeQueueEntry != null),
# the promotion workflow must:
#   1. Detect the existing queued mergeQueueEntry before branch mutation.
#   2. Avoid all branch rewrites (no git checkout -B, git commit, git push --force, or git push --delete).
#   3. Report an informative notice and exit successfully (code 0) with promoted=false.
#   4. Never attempt to dequeue the PR or bypass merge queue protection.
#
# When no PR is queued (mergeQueueEntry == null or no open PR), it proceeds past the guard.

setup() {
  TEST_TMP="${BATS_TEST_DIRNAME}/scratch_queue_guard_${BATS_TEST_NUMBER}_$$"
  mkdir -p "$TEST_TMP/bin"
  export TEST_TMP
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  export MOCK_DIR="${TEST_TMP}/bin"
  export PATH="${MOCK_DIR}:${PATH}"

  export GITHUB_REPOSITORY="projectbluefin/bluefin"
  export PROMOTION_BRANCH="auto/promote-testing-to-main"
  export TARGET_BRANCH="main"
  export SOURCE_BRANCH="testing"
  export GH_TOKEN="mock-token-xyz"

  export GH_LOG_FILE="${TEST_TMP}/gh_calls.log"
  export GIT_LOG_FILE="${TEST_TMP}/git_calls.log"
  export GIT_PUSH_LOG_FILE="${TEST_TMP}/git_push_calls.log"
  export GRAPHQL_RESPONSE_FILE="${TEST_TMP}/graphql_response.json"

  REAL_GIT_BIN=$(which git)
  export REAL_GIT_BIN

  # Default mock gh: records call and returns GRAPHQL_RESPONSE_FILE for `gh api graphql`
  cat > "${MOCK_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
echo "gh $*" >> "${GH_LOG_FILE}"
if [ "$1" = "api" ] && [ "$2" = "graphql" ]; then
  jq_filter=""
  prev=""
  for arg in "$@"; do
    if [ "$prev" = "--jq" ]; then
      jq_filter="$arg"
      break
    fi
    prev="$arg"
  done
  if [ -f "${GRAPHQL_RESPONSE_FILE}" ]; then
    if [ -n "$jq_filter" ]; then
      jq -c "$jq_filter" "${GRAPHQL_RESPONSE_FILE}"
    else
      cat "${GRAPHQL_RESPONSE_FILE}"
    fi
  else
    echo '{"data":{"repository":{"pullRequests":{"nodes":[]}}}}'
  fi
  exit "${GRAPHQL_EXIT_CODE:-0}"
fi
echo "mock gh: unexpected invocation: $*" >&2
exit 1
EOF
  chmod +x "${MOCK_DIR}/gh"

  # Default mock git: logs all calls, intercepts git push to check/simulate GH006
  cat > "${MOCK_DIR}/git" <<'EOF'
#!/usr/bin/env bash
echo "git $*" >> "${GIT_LOG_FILE}"
if [ "$1" = "push" ]; then
  echo "git $*" >> "${GIT_PUSH_LOG_FILE}"
  if [ "${SIMULATE_GH006:-0}" = "1" ]; then
    echo "remote: error: GH006: Ref cannot be updated: A pull request using this branch as its head is in the merge queue and cannot be modified." >&2
    exit 1
  fi
fi
# Minimal mocks for rev-parse, write-tree, diff, checkout, add, commit
case "$1" in
  rev-parse)
    if [ "${EXISTING_TREE_DIFFERS:-0}" = "1" ]; then
      echo "different_tree_sha_1234567890"
    else
      echo "0123456789abcdef0123456789abcdef01234567"
    fi
    exit 0
    ;;
  write-tree)
    echo "0123456789abcdef0123456789abcdef01234567"
    exit 0
    ;;
  diff)
    # Return non-empty diff by default so it doesn't take the "squash diff empty" branch
    if [ "$2" = "--cached" ] && [ "$3" = "--quiet" ]; then
      exit 1
    fi
    exit 0
    ;;
  checkout|add|commit)
    exit 0
    ;;
  push)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
EOF
  chmod +x "${MOCK_DIR}/git"
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

load_rebuild_logic() {
  local workflow_file="${BATS_TEST_DIRNAME}/../../.github/workflows/reusable-promote-squash.yml"
  python3 -c "
import yaml
with open('${workflow_file}') as f:
    wf = yaml.safe_load(f)
steps = wf['jobs']['promote']['steps']
rebuild_step = next(s for s in steps if s.get('id') == 'rebuild')
print(rebuild_step['run'])
"
}

@test "queued PR with active mergeQueueEntry: avoids branch mutation, reports notice, sets promoted=false, and exits 0" {
  cat > "$GRAPHQL_RESPONSE_FILE" <<'JSON'
{
  "data": {
    "repository": {
      "pullRequests": {
        "nodes": [
          {
            "id": "PR_kwDOSsGX088AAAABAO2i8A",
            "number": 1115,
            "url": "https://github.com/projectbluefin/bluefin/pull/1115",
            "mergeQueueEntry": {
              "id": "MQE_lADOB0tUAc5k2w_zgAAb-3Y",
              "state": "QUEUED"
            }
          }
        ]
      }
    }
  }
}
JSON

  export SIMULATE_GH006=1
  REBUILD_LOGIC=$(load_rebuild_logic)

  run bash -c "$REBUILD_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::notice::"* ]]
  [[ "$output" == *"1115"* ]]
  [[ "$output" == *"merge queue entry"* ]]
  [[ "$output" == *"skipping branch mutation"* ]]
  [ "$(get_output promoted)" = "false" ]
}

@test "queued PR with active mergeQueueEntry: git push is never attempted (GH006 prevented)" {
  cat > "$GRAPHQL_RESPONSE_FILE" <<'JSON'
{
  "data": {
    "repository": {
      "pullRequests": {
        "nodes": [
          {
            "id": "PR_kwDOSsGX088AAAABAO2i8A",
            "number": 1115,
            "url": "https://github.com/projectbluefin/bluefin/pull/1115",
            "mergeQueueEntry": {
              "id": "MQE_lADOB0tUAc5k2w_zgAAb-3Y",
              "state": "QUEUED"
            }
          }
        ]
      }
    }
  }
}
JSON

  export SIMULATE_GH006=1
  REBUILD_LOGIC=$(load_rebuild_logic)

  run bash -c "$REBUILD_LOGIC"
  [ "$status" -eq 0 ]
  [ ! -f "$GIT_PUSH_LOG_FILE" ]
  # Verify git checkout -B was not called
  if [ -f "$GIT_LOG_FILE" ]; then
    run grep -E "checkout -B" "$GIT_LOG_FILE"
    [ "$status" -ne 0 ]
  fi
}

@test "queued PR with active mergeQueueEntry: dequeue is never called" {
  cat > "$GRAPHQL_RESPONSE_FILE" <<'JSON'
{
  "data": {
    "repository": {
      "pullRequests": {
        "nodes": [
          {
            "id": "PR_kwDOSsGX088AAAABAO2i8A",
            "number": 1115,
            "url": "https://github.com/projectbluefin/bluefin/pull/1115",
            "mergeQueueEntry": {
              "id": "MQE_lADOB0tUAc5k2w_zgAAb-3Y",
              "state": "QUEUED"
            }
          }
        ]
      }
    }
  }
}
JSON

  REBUILD_LOGIC=$(load_rebuild_logic)

  run bash -c "$REBUILD_LOGIC"
  [ "$status" -eq 0 ]
  # Verify dequeuePullRequest was never invoked
  if [ -f "$GH_LOG_FILE" ]; then
    run grep -i "dequeue" "$GH_LOG_FILE"
    [ "$status" -ne 0 ]
  fi
}

@test "PR without mergeQueueEntry (null): proceeds past guard to rebuild and push" {
  cat > "$GRAPHQL_RESPONSE_FILE" <<'JSON'
{
  "data": {
    "repository": {
      "pullRequests": {
        "nodes": [
          {
            "id": "PR_kwDOSsGX088AAAABAO2i8A",
            "number": 1115,
            "url": "https://github.com/projectbluefin/bluefin/pull/1115",
            "mergeQueueEntry": null
          }
        ]
      }
    }
  }
}
JSON

  export EXISTING_TREE_DIFFERS=1
  REBUILD_LOGIC=$(load_rebuild_logic)

  run bash -c "$REBUILD_LOGIC"
  [ "$status" -eq 0 ]
  # Since mergeQueueEntry is null, rebuild must have proceeded to git push
  [ -f "$GIT_PUSH_LOG_FILE" ]
  [ "$(get_output promoted)" != "false" ]
}

@test "no open PR exists: proceeds past guard to rebuild and push" {
  cat > "$GRAPHQL_RESPONSE_FILE" <<'JSON'
{
  "data": {
    "repository": {
      "pullRequests": {
        "nodes": []
      }
    }
  }
}
JSON

  export EXISTING_TREE_DIFFERS=1
  REBUILD_LOGIC=$(load_rebuild_logic)

  run bash -c "$REBUILD_LOGIC"
  [ "$status" -eq 0 ]
  # No open PR exists, so rebuild must proceed to git push
  [ -f "$GIT_PUSH_LOG_FILE" ]
  [ "$(get_output promoted)" != "false" ]
}

@test "queued PR in AWAITING_CHECKS state: detected, outputs pr_number and pr_url" {
  cat > "$GRAPHQL_RESPONSE_FILE" <<'JSON'
{
  "data": {
    "repository": {
      "pullRequests": {
        "nodes": [
          {
            "id": "PR_kwDOSsGX088AAAABAO2i8A",
            "number": 1115,
            "url": "https://github.com/projectbluefin/bluefin/pull/1115",
            "mergeQueueEntry": {
              "id": "MQE_awaiting_checks_123",
              "state": "AWAITING_CHECKS"
            }
          }
        ]
      }
    }
  }
}
JSON

  REBUILD_LOGIC=$(load_rebuild_logic)

  run bash -c "$REBUILD_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"AWAITING_CHECKS"* ]]
  [ "$(get_output promoted)" = "false" ]
  [ "$(get_output pr_number)" = "1115" ]
  [ "$(get_output pr_url)" = "https://github.com/projectbluefin/bluefin/pull/1115" ]
}

@test "queued PR: git push --delete is never attempted" {
  cat > "$GRAPHQL_RESPONSE_FILE" <<'JSON'
{
  "data": {
    "repository": {
      "pullRequests": {
        "nodes": [
          {
            "id": "PR_kwDOSsGX088AAAABAO2i8A",
            "number": 1115,
            "url": "https://github.com/projectbluefin/bluefin/pull/1115",
            "mergeQueueEntry": {
              "id": "MQE_lADOB0tUAc5k2w_zgAAb-3Y",
              "state": "QUEUED"
            }
          }
        ]
      }
    }
  }
}
JSON

  REBUILD_LOGIC=$(load_rebuild_logic)

  run bash -c "$REBUILD_LOGIC"
  [ "$status" -eq 0 ]
  if [ -f "$GIT_LOG_FILE" ]; then
    run grep -E "push.*--delete" "$GIT_LOG_FILE"
    [ "$status" -ne 0 ]
  fi
}

@test "GraphQL API error: handles gracefully and does not crash" {
  export GRAPHQL_EXIT_CODE=1
  export EXISTING_TREE_DIFFERS=1
  REBUILD_LOGIC=$(load_rebuild_logic)

  run bash -c "$REBUILD_LOGIC"
  [ "$status" -eq 0 ]
  # In case of API failure, it safely proceeds past the guard without crashing
  [ -f "$GIT_PUSH_LOG_FILE" ]
}

@test "rebuild step queue-guard GraphQL query has shellcheck disable annotation for SC2016" {
  local workflow_file="${BATS_TEST_DIRNAME}/../../.github/workflows/reusable-promote-squash.yml"
  run grep -B 1 "PR_DATA=\$(gh api graphql" "$workflow_file"
  [ "$status" -eq 0 ]
  [[ "$output" == *"# shellcheck disable=SC2016"* ]]
}
