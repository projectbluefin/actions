#!/usr/bin/env bash
# Extracted from bootc-build/generate-tags/action.yml — called by action.yml step.
# All inputs are passed as environment variables (see action.yml env: block).
#
# Required env vars:
#   BASE_NAME       - base image name (e.g. bluefin, aurora)
#   STREAM          - stream name (e.g. latest, stable, testing, beta)
#   FLAVOR          - image flavor (e.g. main, nvidia, hwe)
#   KERNEL_PIN      - optional kernel pin string (e.g. 6.14.9-200.fc42.x86_64)
#   VERSION_LABEL   - OCI org.opencontainers.image.version label value
#   EVENT_NAME      - GitHub event name (github.event_name)
#   PR_NUMBER       - PR number (required for pull_request events)
#
# Outputs (written to $GITHUB_OUTPUT):
#   tags            - space-separated list of OCI tags
#   default_tag     - primary tag used for signing and digest capture

set -euo pipefail

# ── Default tag ──────────────────────────────────────────────────────────────
# stable streams use "stable-daily" as the mutable push target so the
# immutable "stable" tag is only moved on promotion day.
if [[ "${STREAM}" =~ stable ]]; then
  DEFAULT_TAG="stable-daily"
else
  DEFAULT_TAG="${STREAM}"
fi

# ── Version string ───────────────────────────────────────────────────────────
# Strip leading "<stream>-" or "stable-daily-" prefix if present.
# Rechunk may set labels like "latest-42.20250531"; plain builds emit
# "42.20250531" directly.  After stripping: version="42.20250531".
version="${VERSION_LABEL#${STREAM}-}"
version="${version#stable-daily-}"

# Short date suffix: everything after the first dot.
# "42.20250531" → "20250531"  (works for any-width Fedora version)
version_date="${version#*.}"

# ── Fedora version ───────────────────────────────────────────────────────────
# Derived from normalized version (safe against stream-prefixed labels).
# Prefer kernel-pin override (e.g. 6.14.9-200.fc42.x86_64 → 42).
if [[ -n "${KERNEL_PIN}" ]]; then
  FEDORA_VERSION="$(echo "${KERNEL_PIN}" | grep -oP 'fc\K[0-9]+')"
else
  FEDORA_VERSION="${version%%.*}"
fi

# ── Tag arrays ───────────────────────────────────────────────────────────────
BUILD_TAGS=()
COMMIT_TAGS=()

# Build/convenience tags — used for non-PR events
if [[ "${STREAM}" =~ stable ]]; then
  BUILD_TAGS+=("stable-daily" "${version}" "stable-daily-${version}" "stable-daily-${version_date}")
else
  BUILD_TAGS+=("${STREAM}" "${STREAM}-${version}" "${STREAM}-${version_date}")
  # latest stream also receives stable-daily aliases for compatibility
  if [[ "${STREAM}" == "latest" ]]; then
    BUILD_TAGS+=("stable-daily" "stable-daily-${version}" "stable-daily-${version_date}")
  fi
fi

# Promotion tags: added on schedule (Tuesday) or explicit dispatch
TODAY="$(date +%A)"
if [[ "${STREAM}" =~ stable && "${TODAY}" == "Tuesday" && "${EVENT_NAME}" =~ schedule ]]; then
  BUILD_TAGS+=("stable" "stable-${version}" "stable-${version_date}" "gts" "gts-${version}" "gts-${version_date}")
elif [[ "${STREAM}" =~ stable && "${EVENT_NAME}" =~ workflow_dispatch|workflow_call ]]; then
  BUILD_TAGS+=("stable" "stable-${version}" "stable-${version_date}" "gts" "gts-${version}" "gts-${version_date}")
elif [[ ! "${STREAM}" =~ stable|beta && "${STREAM}" != "testing" ]]; then
  # Non-stable/non-beta/non-testing streams (e.g. latest) also get numeric Fedora version tags
  BUILD_TAGS+=("${FEDORA_VERSION}" "${FEDORA_VERSION}-${version}" "${FEDORA_VERSION}-${version_date}")
fi

# ── Select tag set ───────────────────────────────────────────────────────────
if [[ "${EVENT_NAME}" == "pull_request" ]]; then
  # PR commit tags — computed only here to avoid unbound-variable errors
  # under set -u when PR_NUMBER is empty on non-PR events.
  SHA_SHORT="${GITHUB_SHA::7}"
  COMMIT_TAGS+=("pr-${PR_NUMBER:-}-${STREAM}-${version}")
  COMMIT_TAGS+=("${SHA_SHORT}-${STREAM}-${version}")
  alias_tags=("${COMMIT_TAGS[@]}")
else
  alias_tags=("${BUILD_TAGS[@]}")
fi

echo "Default tag: ${DEFAULT_TAG}"
echo "Tags: ${alias_tags[*]}"

echo "default_tag=${DEFAULT_TAG}" >> "$GITHUB_OUTPUT"
echo "tags=${alias_tags[*]}" >> "$GITHUB_OUTPUT"
