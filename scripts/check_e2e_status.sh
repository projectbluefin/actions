#!/usr/bin/env bash
# Query the source commit's producer-published E2E status and emit gate outputs.

set -euo pipefail

if [ "$RUN_E2E" != 'true' ]; then
  {
    echo 'ok=true'
    echo 'state=skipped'
    echo 'summary=E2E check disabled by caller.'
    echo 'details=Caller disabled the E2E gate.'
    echo 'last_status=skipped'
    echo 'last_age_minutes='
    echo 'last_run_url='
    echo 'workflow_path='
  } >> "$GITHUB_OUTPUT"
  exit 0
fi

if [ -z "$E2E_IMAGE" ]; then
  {
    echo 'ok=true'
    echo 'state=skipped'
    echo 'summary=E2E image not set; E2E gate skipped.'
    echo 'details=Caller left e2e_image empty.'
    echo 'last_status=skipped'
    echo 'last_age_minutes='
    echo 'last_run_url='
    echo 'workflow_path='
  } >> "$GITHUB_OUTPUT"
  exit 0
fi

statuses=$(gh api \
  -H 'Accept: application/vnd.github+json' \
  "/repos/${REPO}/commits/${HEAD_SHA}/status")

selected=$(jq -c --arg context "$E2E_STATUS_CONTEXT" '
  [
    .statuses[]
    | select(.context == $context)
    | select((.avatar_url // "") | test("/in/15368([?]|$)"))
  ]
  | sort_by(.updated_at)
  | reverse
  | .[0] // empty
' <<<"$statuses")

if [ -z "$selected" ]; then
  {
    echo 'ok=false'
    echo 'state=waiting'
    echo "summary=No trusted ${E2E_STATUS_CONTEXT} status found for suites ${E2E_SUITES} on source commit ${HEAD_SHA}."
    echo 'details=Expected the GitHub Actions producer workflow to publish a commit status after testing this exact source commit.'
    echo 'last_status=missing'
    echo 'last_age_minutes='
    echo 'last_run_url='
    echo 'workflow_path='
  } >> "$GITHUB_OUTPUT"
  exit 0
fi

status=$(jq -r '.state // "unknown"' <<<"$selected")
target_url=$(jq -r '.target_url // empty' <<<"$selected")
description=$(jq -r '.description // empty' <<<"$selected")
updated_at=$(jq -r '.updated_at // empty' <<<"$selected")
age_minutes=""
if [ -n "$updated_at" ]; then
  age_minutes=$(( ( $(date -u +%s) - $(date -d "$updated_at" +%s) ) / 60 ))
fi

if [ "$status" = 'success' ]; then
  {
    echo 'ok=true'
    echo 'state=passed'
    echo "summary=${E2E_STATUS_CONTEXT} passed for suites ${E2E_SUITES} on source commit ${HEAD_SHA}."
    echo "details=${target_url:-$description}"
    echo 'last_status=success'
    echo "last_age_minutes=${age_minutes}"
    echo "last_run_url=${target_url}"
    echo 'workflow_path='
  } >> "$GITHUB_OUTPUT"
else
  {
    echo 'ok=false'
    echo 'state=failed'
    echo "summary=${E2E_STATUS_CONTEXT} is ${status} for suites ${E2E_SUITES} on source commit ${HEAD_SHA}."
    echo "details=${target_url:-$description}"
    echo "last_status=${status}"
    echo "last_age_minutes=${age_minutes}"
    echo "last_run_url=${target_url}"
    echo 'workflow_path='
  } >> "$GITHUB_OUTPUT"
fi
