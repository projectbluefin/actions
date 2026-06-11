#!/usr/bin/env bash
# Extracted from .github/workflows/reusable-release-gate.yml — "Resolve digests" step.
# Resolves OCI image tags to SHA digests via skopeo.
#
# Required env vars:
#   REGISTRY       - GHCR registry prefix (e.g. ghcr.io/projectbluefin)
#   TARGET_TAG     - Source tag to resolve (e.g. testing)
#   VARIANTS_JSON  - JSON array of image variants (strings or {image:...} objects)
#
# Outputs written to $GITHUB_OUTPUT:
#   ok             - "true" if all digests resolved, "false" otherwise
#   summary        - Human-readable summary
#   digests        - JSON object mapping image→digest
#   rows           - Multiline table rows (image|digest)

set -euo pipefail
digests='{}'
rows=''
failed=0
count=0

while IFS= read -r variant; do
  [ -n "$variant" ] || continue
  image=$(jq -r 'if type == "string" then . else .image end' <<<"$variant")
  count=$((count + 1))
  ref="${REGISTRY}/${image}:${TARGET_TAG}"

  if digest=$(skopeo inspect --format '{{.Digest}}' "docker://${ref}" 2>/dev/null); then
    digests=$(jq -c --arg image "$image" --arg digest "$digest" '. + {($image): $digest}' <<<"$digests")
    rows+="${image}|${digest}"$'\n'
  else
    failed=1
    rows+="${image}|ERROR"$'\n'
  fi
done < <(jq -c '.[]' <<<"$VARIANTS_JSON")

if [ "$failed" -eq 0 ]; then
  ok=true
  summary="Resolved ${count} digest(s) from ${TARGET_TAG}."
else
  ok=false
  summary="Failed to resolve one or more digests from ${TARGET_TAG}."
fi

{
  echo "ok=${ok}"
  echo "summary=${summary}"
  echo "digests=${digests}"
  echo 'rows<<EOF'
  printf '%s' "$rows"
  echo 'EOF'
} >> "$GITHUB_OUTPUT"
