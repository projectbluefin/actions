#!/usr/bin/env bash
# Extracted from .github/workflows/reusable-release-gate.yml — "Verify cosign signatures" step.
# Verifies cosign signatures for resolved digests.
#
# Required env vars:
#   DIGESTS_JSON       - JSON object mapping image→digest (from resolve_digests.sh)
#   IDENTITY_REGEXP    - Regexp for cosign --certificate-identity-regexp
#   REGISTRY           - GHCR registry prefix
#   VARIANTS_JSON      - JSON array of image variants
#   RESOLVE_OK         - "true" if digest resolution succeeded
#
# Outputs written to $GITHUB_OUTPUT:
#   ok                 - "true" if all signatures verified
#   summary            - Human-readable summary
#   results            - JSON object mapping image→"passed"|"failed"
#   rows               - Multiline table rows (image|status|detail)

set -euo pipefail
results='{}'
rows=''
failed=0

if [ "${RESOLVE_OK}" != 'true' ]; then
  {
    echo 'ok=false'
    echo 'summary=Skipped signature verification because digest resolution failed.'
    echo 'results={}'
    echo 'rows<<EOF'
    echo 'EOF'
  } >> "$GITHUB_OUTPUT"
  exit 0
fi

while IFS= read -r variant; do
  [ -n "$variant" ] || continue
  image=$(jq -r 'if type == "string" then . else .image end' <<<"$variant")
  digest=$(jq -r --arg image "$image" '.[$image] // empty' <<<"$DIGESTS_JSON")

  if [ -z "$digest" ]; then
    failed=1
    results=$(jq -c --arg image "$image" '. + {($image): "failed"}' <<<"$results")
    rows+="${image}|failed|digest missing"$'\n'
    continue
  fi

  ref="${REGISTRY}/${image}@${digest}"
  if cosign verify \
    --certificate-identity-regexp "$IDENTITY_REGEXP" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
    "$ref" >/dev/null 2>&1; then
    results=$(jq -c --arg image "$image" '. + {($image): "passed"}' <<<"$results")
    rows+="${image}|passed|signature verified"$'\n'
  else
    failed=1
    results=$(jq -c --arg image "$image" '. + {($image): "failed"}' <<<"$results")
    rows+="${image}|failed|signature verification failed"$'\n'
  fi
done < <(jq -c '.[]' <<<"$VARIANTS_JSON")

if [ "$failed" -eq 0 ]; then
  ok=true
  summary='All resolved digests passed cosign verification.'
else
  ok=false
  summary='One or more digests failed cosign verification.'
fi

{
  echo "ok=${ok}"
  echo "summary=${summary}"
  echo "results=${results}"
  echo 'rows<<EOF'
  printf '%s' "$rows"
  echo 'EOF'
} >> "$GITHUB_OUTPUT"
