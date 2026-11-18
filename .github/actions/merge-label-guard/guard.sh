#!/usr/bin/env bash
# Invoke immediately before each merge-enabling write. Never execute PR-head code.
set -euo pipefail

labels=$(gh api "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/labels?per_page=100" --paginate --slurp)
blocked=$(jq -er '
  if type != "array" or length == 0 then error("missing label pages")
  elif any(.[]; type != "array") then error("invalid label page")
  elif any(.[][]; (.name | type) != "string") then error("invalid label name")
  else [ .[][].name | ascii_downcase
         | . == "hold" or . == "do-not-merge" or startswith("do-not-merge/") ]
       | any | tostring
  end' <<<"$labels")
echo "blocked=$blocked" >> "$GITHUB_OUTPUT"
[ "$blocked" = true ] || exit 0

echo "::notice::PR #${PR_NUMBER} has a merge-blocking label; merge/enrollment skipped."
# Only withdraw enrollment owned by this token's actor, never a maintainer's or
# another app's. Unknown ownership and API failures must not permit a merge.
# shellcheck disable=SC2016  # GraphQL variables, not shell variables
state=$(gh api graphql \
  -f owner="${GITHUB_REPOSITORY%/*}" -f repo="${GITHUB_REPOSITORY#*/}" -F number="$PR_NUMBER" \
  -f query='query($owner:String!,$repo:String!,$number:Int!){viewer{id} repository(owner:$owner,name:$repo){pullRequest(number:$number){id autoMergeRequest{enabledBy{... on User{id} ... on Bot{id}}} mergeQueueEntry{enqueuer{... on User{id} ... on Bot{id}}}}}}')
jq -e '(.errors // [] | length) == 0 and (.data.viewer.id | type == "string" and length > 0) and (.data.repository.pullRequest.id | type == "string" and length > 0)' <<<"$state" >/dev/null
node_id=$(jq -r '.data.repository.pullRequest.id' <<<"$state")
if jq -e '.data.viewer.id == .data.repository.pullRequest.autoMergeRequest.enabledBy.id' <<<"$state" >/dev/null; then
  # shellcheck disable=SC2016
  gh api graphql -f id="$node_id" \
    -f query='mutation($id:ID!){disablePullRequestAutoMerge(input:{pullRequestId:$id}){clientMutationId}}' >/dev/null
fi
if jq -e '.data.viewer.id == .data.repository.pullRequest.mergeQueueEntry.enqueuer.id' <<<"$state" >/dev/null; then
  # shellcheck disable=SC2016
  gh api graphql -f id="$node_id" \
    -f query='mutation($id:ID!){dequeuePullRequest(input:{id:$id}){clientMutationId}}' >/dev/null
fi
exit 3
