#!/usr/bin/env bash
# retry.sh — exponential-backoff retry for composite action
#
# Environment variables (set by action.yml):
#   RETRY_COMMAND         Shell command to execute (eval'd)
#   MAX_ATTEMPTS          Maximum number of attempts (default: 3)
#   INITIAL_WAIT_SECONDS  Wait before retry attempt 2; doubles each time (default: 10)
#   RETRY_ON              Regex: only retry when stderr matches (empty = always retry)
#
# Outputs written to $GITHUB_OUTPUT:
#   attempts=<n>          How many attempts were made
#   success=true|false    Whether the command eventually succeeded

set -euo pipefail

MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
INITIAL_WAIT_SECONDS="${INITIAL_WAIT_SECONDS:-10}"
RETRY_ON="${RETRY_ON:-}"

attempts=0
wait_seconds="${INITIAL_WAIT_SECONDS}"

while true; do
  attempts=$(( attempts + 1 ))

  # Capture stderr while still passing stdout/stdin through
  stderr_file=$(mktemp)
  rc=0
  eval "${RETRY_COMMAND}" 2> >(tee "${stderr_file}" >&2) || rc=$?

  if [ "${rc}" -eq 0 ]; then
    rm -f "${stderr_file}"
    echo "attempts=${attempts}" >> "${GITHUB_OUTPUT}"
    echo "success=true" >> "${GITHUB_OUTPUT}"
    exit 0
  fi

  # Pattern check: if RETRY_ON is set, only retry when stderr matches
  if [ -n "${RETRY_ON}" ]; then
    if ! grep -qiE "${RETRY_ON}" "${stderr_file}" 2>/dev/null; then
      rm -f "${stderr_file}"
      echo "::warning::non-retryable error on attempt ${attempts}; giving up."
      echo "attempts=${attempts}" >> "${GITHUB_OUTPUT}"
      echo "success=false" >> "${GITHUB_OUTPUT}"
      exit "${rc}"
    fi
  fi

  rm -f "${stderr_file}"

  if [ "${attempts}" -ge "${MAX_ATTEMPTS}" ]; then
    echo "::warning::command failed after ${attempts} attempt(s)."
    echo "attempts=${attempts}" >> "${GITHUB_OUTPUT}"
    echo "success=false" >> "${GITHUB_OUTPUT}"
    exit "${rc}"
  fi

  echo "::warning::attempt ${attempts}/${MAX_ATTEMPTS} failed; retrying in ${wait_seconds}s..."
  sleep "${wait_seconds}"
  wait_seconds=$(( wait_seconds * 2 ))
done
