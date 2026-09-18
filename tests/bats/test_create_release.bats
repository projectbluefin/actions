#!/usr/bin/env bats
# Tests for the bootc-build/create-release composite action's inline shell steps.
#
# The shell logic lives inline in bootc-build/create-release/action.yml.
# We extract it here verbatim (one variable per step) so any edit to the action
# that changes testable behavior must also update this file. This mirrors the
# convention already used by tests/bats/test_push_image.bats and friends.
#
# Every other action under bootc-build/ has a bats suite; create-release did
# not, so none of these branches were executed by CI:
#
#   Validate SBOM        - missing file, non-SPDX JSON, valid SPDX
#   Fetch previous SBOM  - no prior release, asset present, asset absent
#   Write optional input - variants/extra-components written only when non-empty
#   Render release card  - YYYY-MM-DD-SHA7 tag parsing vs. semver fallback
#   Resolve SBOM name    - explicit sbom-filename vs. basename fallback
#   Detect overflow      - release-notes-full.md present or not
#   Create release       - idempotent skip, draft/prerelease flags, overflow asset

# ── Step logic, verbatim from bootc-build/create-release/action.yml ──────────

VALIDATE_SBOM_LOGIC=$(cat <<'BATS_STEP_EOF'
set -euo pipefail
if [[ ! -f "${SBOM_PATH}" ]]; then
  echo "::error::SBOM not found at '${SBOM_PATH}'"
  exit 1
fi
# Verify it is valid SPDX-JSON (has spdxVersion key)
if ! python3 -c "
import json, sys
with open('${SBOM_PATH}') as f:
    d = json.load(f)
if 'spdxVersion' not in d:
    print('Missing spdxVersion — not a valid SPDX document', file=sys.stderr)
    sys.exit(1)
print(f'SPDX {d[\"spdxVersion\"]} — {len(d.get(\"packages\", []))} packages')
"; then
  echo "::error::${SBOM_PATH} is not a valid SPDX-JSON document"
  exit 1
fi
BATS_STEP_EOF
)

PREV_SBOM_LOGIC=$(cat <<'BATS_STEP_EOF'
set -euo pipefail
PREV_TAG=$(gh release list \
  --repo "${REPO}" \
  --limit 1 \
  --json tagName \
  --jq '.[0].tagName' 2>/dev/null || true)

if [[ -z "${PREV_TAG}" ]]; then
  echo "No previous release — first release, skipping diff."
  echo "found=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

mkdir -p _sbom_prev
# Accept any .spdx.json asset from the previous release
if gh release download "${PREV_TAG}" \
    --repo "${REPO}" \
    --pattern "*.spdx.json" \
    --dir _sbom_prev 2>/dev/null; then
  PREV_FILE=$(ls _sbom_prev/*.spdx.json | head -n1)
  echo "found=true"          >> "$GITHUB_OUTPUT"
  echo "path=${PREV_FILE}"   >> "$GITHUB_OUTPUT"
  echo "tag=${PREV_TAG}"     >> "$GITHUB_OUTPUT"
  echo "Previous SBOM: ${PREV_FILE} (from ${PREV_TAG})"
else
  echo "::warning::No .spdx.json asset in release ${PREV_TAG} — skipping diff"
  echo "found=false" >> "$GITHUB_OUTPUT"
fi
BATS_STEP_EOF
)

OPTIONAL_INPUTS_LOGIC=$(cat <<'BATS_STEP_EOF'
set -euo pipefail
[[ -n "${VARIANTS_JSON:-}" ]]         && echo "${VARIANTS_JSON}"         > _variants.json
[[ -n "${EXTRA_COMPONENTS_JSON:-}" ]] && echo "${EXTRA_COMPONENTS_JSON}" > _extra_components.json
true
BATS_STEP_EOF
)

RENDER_CARD_LOGIC=$(cat <<'BATS_STEP_EOF'
set -euo pipefail
# Extract date and sha7 from tag.
# Supports: YYYY-MM-DD-SHA7 (date+sha tags used by dakota/bluefin-lts)
# Falls back to today's date and last 7 chars of the tag for semver tags.
if [[ "${TAG}" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2})-([0-9a-f]{7,})$ ]]; then
  DATE="${BASH_REMATCH[1]}"
  SHA7="${BASH_REMATCH[2]:0:7}"
else
  DATE="$(date -u +%Y-%m-%d)"
  SHA7="${TAG: -7}"
fi

python3 "${ACTION_PATH}/scripts/render_card.py" \
  --versions     _versions.json \
  --tag          "${TAG}" \
  --date         "${DATE}" \
  --sha7         "${SHA7}" \
  --project-name "${PROJECT_NAME}" \
  --accent-color "${ACCENT_COLOR}" \
  --badge-label  "${BADGE_LABEL}" \
  --image-ref    "${IMAGE}" \
  --docs-url     "${DOCS_URL}" \
  --output       release-card.png
BATS_STEP_EOF
)

SBOM_NAME_LOGIC=$(cat <<'BATS_STEP_EOF'
set -euo pipefail
if [[ -n "${SBOM_FILENAME}" ]]; then
  TARGET="${SBOM_FILENAME}"
else
  TARGET="$(basename "${SBOM_PATH}")"
fi
# Copy SBOM to cwd with target filename so it's easy to attach
cp "${SBOM_PATH}" "${TARGET}"
echo "filename=${TARGET}" >> "$GITHUB_OUTPUT"
BATS_STEP_EOF
)

OVERFLOW_LOGIC=$(cat <<'BATS_STEP_EOF'
set -euo pipefail
if [[ -f "release-notes-full.md" ]]; then
  echo "found=true" >> "$GITHUB_OUTPUT"
  echo "Overflow notes detected — will attach release-notes-full.md as a release asset."
else
  echo "found=false" >> "$GITHUB_OUTPUT"
fi
BATS_STEP_EOF
)

CREATE_RELEASE_LOGIC=$(cat <<'BATS_STEP_EOF'
set -euo pipefail

# Idempotent: skip if this tag already exists
if gh release view "${TAG}" --repo "${REPO}" &>/dev/null; then
  echo "Release ${TAG} already exists — skipping."
  URL=$(gh release view "${TAG}" --repo "${REPO}" --json url --jq '.url')
  echo "url=${URL}" >> "$GITHUB_OUTPUT"
  exit 0
fi

DRAFT_FLAG=""
[[ "${DRAFT}" == "true" ]]      && DRAFT_FLAG="--draft"
PRERELEASE_FLAG=""
[[ "${PRERELEASE}" == "true" ]] && PRERELEASE_FLAG="--prerelease"

# Attach the full-notes overflow asset when the body was trimmed.
OVERFLOW_ASSETS=()
if [[ "${OVERFLOW_FOUND}" == "true" ]]; then
  OVERFLOW_ASSETS+=("release-notes-full.md")
fi

URL=$(gh release create "${TAG}" \
  --repo           "${REPO}" \
  --title          "${TITLE}" \
  --notes-file     release-notes.md \
  ${DRAFT_FLAG} \
  ${PRERELEASE_FLAG} \
  release-card.png \
  release-card-dark.png \
  "${SBOM_FILENAME}" \
  "${OVERFLOW_ASSETS[@]}" \
  | tail -n1)

echo "url=${URL}" >> "$GITHUB_OUTPUT"
echo "Created release: ${URL}"
BATS_STEP_EOF
)

setup() {
  TEST_TMP=$(mktemp -d)
  cd "$TEST_TMP" || return 1

  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  export GH_CALL_LOG="${TEST_TMP}/gh_calls"
  export PY_CALL_LOG="${TEST_TMP}/py_calls"
  touch "$GH_CALL_LOG" "$PY_CALL_LOG"

  # Defaults shared by the release steps
  export REPO="projectbluefin/actions"
  export TAG="2026-01-02-abcdef1"
  export TITLE="Test release"
  export DRAFT="false"
  export PRERELEASE="false"
  export OVERFLOW_FOUND="false"
  export SBOM_FILENAME=""
}

teardown() {
  cd / || true
  rm -rf "$TEST_TMP"
}

# gh mock: behavior driven by GH_* env vars, every call appended to GH_CALL_LOG
stub_gh() {
  cat > "${MOCK_DIR}/gh" << 'EOF'
#!/usr/bin/env bash
echo "$*" >> "$GH_CALL_LOG"
case "$2" in
  list)
    printf '%s' "${GH_PREV_TAG:-}"
    [[ -n "${GH_PREV_TAG:-}" ]] && echo
    exit "${GH_LIST_RC:-0}"
    ;;
  download)
    if [[ "${GH_DOWNLOAD_RC:-0}" == "0" ]]; then
      dir=""
      while [[ $# -gt 0 ]]; do
        [[ "$1" == "--dir" ]] && dir="$2"
        shift
      done
      mkdir -p "$dir"
      echo '{}' > "${dir}/prev.spdx.json"
    fi
    exit "${GH_DOWNLOAD_RC:-0}"
    ;;
  view)
    [[ "${GH_RELEASE_EXISTS:-false}" == "true" ]] || exit 1
    echo "https://github.com/${REPO}/releases/tag/${TAG}"
    exit 0
    ;;
  create)
    echo "https://github.com/${REPO}/releases/tag/${TAG}"
    exit 0
    ;;
esac
exit 0
EOF
  chmod +x "${MOCK_DIR}/gh"
}

# python3 mock: records argv, does nothing. Only used by render-card tests —
# the Validate SBOM tests deliberately run the real interpreter.
stub_python3() {
  cat > "${MOCK_DIR}/python3" << 'EOF'
#!/usr/bin/env bash
echo "$*" >> "$PY_CALL_LOG"
exit 0
EOF
  chmod +x "${MOCK_DIR}/python3"
}

output_value() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -n1 | cut -d= -f2-
}

# ── Validate SBOM ───────────────────────────────────────────────────────────

@test "validate sbom: missing file fails with an error annotation" {
  export SBOM_PATH="${TEST_TMP}/absent.spdx.json"
  run bash -c "$VALIDATE_SBOM_LOGIC"
  [ "$status" -eq 1 ]
  [[ "$output" == *"::error::SBOM not found at"* ]]
}

@test "validate sbom: JSON without spdxVersion is rejected" {
  export SBOM_PATH="${TEST_TMP}/bad.spdx.json"
  echo '{"packages": []}' > "$SBOM_PATH"
  run bash -c "$VALIDATE_SBOM_LOGIC"
  [ "$status" -eq 1 ]
  [[ "$output" == *"is not a valid SPDX-JSON document"* ]]
}

@test "validate sbom: malformed JSON is rejected" {
  export SBOM_PATH="${TEST_TMP}/broken.spdx.json"
  echo 'not json at all' > "$SBOM_PATH"
  run bash -c "$VALIDATE_SBOM_LOGIC"
  [ "$status" -eq 1 ]
  [[ "$output" == *"is not a valid SPDX-JSON document"* ]]
}

@test "validate sbom: valid SPDX document passes and reports package count" {
  export SBOM_PATH="${TEST_TMP}/good.spdx.json"
  echo '{"spdxVersion": "SPDX-2.3", "packages": [{"name": "a"}, {"name": "b"}]}' > "$SBOM_PATH"
  run bash -c "$VALIDATE_SBOM_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"SPDX-2.3"* ]]
  [[ "$output" == *"2 packages"* ]]
}

# ── Fetch previous SBOM ─────────────────────────────────────────────────────

@test "fetch previous sbom: no prior release sets found=false and skips download" {
  stub_gh
  export GH_PREV_TAG=""
  run bash -c "$PREV_SBOM_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"first release, skipping diff"* ]]
  [ "$(output_value found)" = "false" ]
  run grep -c "release download" "$GH_CALL_LOG"
  [ "$output" = "0" ]
}

@test "fetch previous sbom: gh release list failure is treated as no prior release" {
  stub_gh
  export GH_PREV_TAG=""
  export GH_LIST_RC=1
  run bash -c "$PREV_SBOM_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(output_value found)" = "false" ]
}

@test "fetch previous sbom: downloaded asset sets found, path and tag" {
  stub_gh
  export GH_PREV_TAG="2025-12-31-0000000"
  run bash -c "$PREV_SBOM_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(output_value found)" = "true" ]
  [ "$(output_value path)" = "_sbom_prev/prev.spdx.json" ]
  [ "$(output_value tag)" = "2025-12-31-0000000" ]
}

@test "fetch previous sbom: release without an spdx asset warns and sets found=false" {
  stub_gh
  export GH_PREV_TAG="2025-12-31-0000000"
  export GH_DOWNLOAD_RC=1
  run bash -c "$PREV_SBOM_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::warning::No .spdx.json asset in release 2025-12-31-0000000"* ]]
  [ "$(output_value found)" = "false" ]
}

# ── Write optional inputs ───────────────────────────────────────────────────

@test "optional inputs: both empty leaves no files and still exits 0" {
  export VARIANTS_JSON=""
  export EXTRA_COMPONENTS_JSON=""
  run bash -c "$OPTIONAL_INPUTS_LOGIC"
  [ "$status" -eq 0 ]
  [ ! -f "${TEST_TMP}/_variants.json" ]
  [ ! -f "${TEST_TMP}/_extra_components.json" ]
}

@test "optional inputs: only variants set writes _variants.json and exits 0" {
  export VARIANTS_JSON='["base","dx"]'
  export EXTRA_COMPONENTS_JSON=""
  run bash -c "$OPTIONAL_INPUTS_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(cat "${TEST_TMP}/_variants.json")" = '["base","dx"]' ]
  [ ! -f "${TEST_TMP}/_extra_components.json" ]
}

@test "optional inputs: both set writes both files" {
  export VARIANTS_JSON='["base"]'
  export EXTRA_COMPONENTS_JSON='{"foo":"1.0"}'
  run bash -c "$OPTIONAL_INPUTS_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(cat "${TEST_TMP}/_variants.json")" = '["base"]' ]
  [ "$(cat "${TEST_TMP}/_extra_components.json")" = '{"foo":"1.0"}' ]
}

# ── Render release card: tag parsing ────────────────────────────────────────

setup_card_env() {
  stub_python3
  export ACTION_PATH="${TEST_TMP}/action"
  export PROJECT_NAME="Bluefin"
  export ACCENT_COLOR="#000000"
  export BADGE_LABEL="stable"
  export IMAGE="ghcr.io/projectbluefin/bluefin"
  export DOCS_URL="https://docs.projectbluefin.io"
}

@test "render card: date-and-sha tag yields the embedded date and a 7-char sha" {
  setup_card_env
  export TAG="2026-01-02-abcdef1234567"
  run bash -c "$RENDER_CARD_LOGIC"
  [ "$status" -eq 0 ]
  run cat "$PY_CALL_LOG"
  [[ "$output" == *"--date 2026-01-02"* ]]
  [[ "$output" == *"--sha7 abcdef1"* ]]
}

@test "render card: semver tag falls back to today and the last 7 tag chars" {
  setup_card_env
  export TAG="v1.2.3-rc1"
  run bash -c "$RENDER_CARD_LOGIC"
  [ "$status" -eq 0 ]
  run cat "$PY_CALL_LOG"
  [[ "$output" == *"--date $(date -u +%Y-%m-%d)"* ]]
  [[ "$output" == *"--sha7 2.3-rc1"* ]]
}

@test "render card: uppercase sha in a date tag takes the fallback branch" {
  setup_card_env
  export TAG="2026-01-02-ABCDEF1"
  run bash -c "$RENDER_CARD_LOGIC"
  [ "$status" -eq 0 ]
  run cat "$PY_CALL_LOG"
  [[ "$output" == *"--date $(date -u +%Y-%m-%d)"* ]]
  [[ "$output" == *"--sha7 ABCDEF1"* ]]
}

# ── Resolve SBOM filename ───────────────────────────────────────────────────

@test "resolve sbom filename: explicit sbom-filename wins over the source basename" {
  export SBOM_PATH="${TEST_TMP}/artifacts/original.spdx.json"
  mkdir -p "$(dirname "$SBOM_PATH")"
  echo '{}' > "$SBOM_PATH"
  export SBOM_FILENAME="bluefin-stable.spdx.json"
  run bash -c "$SBOM_NAME_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(output_value filename)" = "bluefin-stable.spdx.json" ]
  [ -f "${TEST_TMP}/bluefin-stable.spdx.json" ]
}

@test "resolve sbom filename: empty sbom-filename falls back to the basename" {
  export SBOM_PATH="${TEST_TMP}/artifacts/original.spdx.json"
  mkdir -p "$(dirname "$SBOM_PATH")"
  echo '{}' > "$SBOM_PATH"
  export SBOM_FILENAME=""
  run bash -c "$SBOM_NAME_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(output_value filename)" = "original.spdx.json" ]
  [ -f "${TEST_TMP}/original.spdx.json" ]
}

# ── Detect overflow notes ───────────────────────────────────────────────────

@test "detect overflow: absent release-notes-full.md sets found=false" {
  run bash -c "$OVERFLOW_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(output_value found)" = "false" ]
}

@test "detect overflow: present release-notes-full.md sets found=true" {
  echo "full notes" > "${TEST_TMP}/release-notes-full.md"
  run bash -c "$OVERFLOW_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(output_value found)" = "true" ]
  [[ "$output" == *"Overflow notes detected"* ]]
}

# ── Create GitHub Release ───────────────────────────────────────────────────

@test "create release: existing tag is idempotent — no create call, url still emitted" {
  stub_gh
  export GH_RELEASE_EXISTS="true"
  run bash -c "$CREATE_RELEASE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"already exists — skipping"* ]]
  [ "$(output_value url)" = "https://github.com/projectbluefin/actions/releases/tag/${TAG}" ]
  run grep -c "release create" "$GH_CALL_LOG"
  [ "$output" = "0" ]
}

@test "create release: new tag creates the release and records the url" {
  stub_gh
  export SBOM_FILENAME="bluefin.spdx.json"
  run bash -c "$CREATE_RELEASE_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(output_value url)" = "https://github.com/projectbluefin/actions/releases/tag/${TAG}" ]
  run cat "$GH_CALL_LOG"
  [[ "$output" == *"release create ${TAG}"* ]]
  [[ "$output" == *"--notes-file release-notes.md"* ]]
  [[ "$output" == *"release-card.png release-card-dark.png bluefin.spdx.json"* ]]
}

@test "create release: draft and prerelease inputs add their flags" {
  stub_gh
  export DRAFT="true"
  export PRERELEASE="true"
  export SBOM_FILENAME="bluefin.spdx.json"
  run bash -c "$CREATE_RELEASE_LOGIC"
  [ "$status" -eq 0 ]
  run cat "$GH_CALL_LOG"
  [[ "$output" == *"--draft"* ]]
  [[ "$output" == *"--prerelease"* ]]
}

@test "create release: default inputs omit the draft and prerelease flags" {
  stub_gh
  export SBOM_FILENAME="bluefin.spdx.json"
  run bash -c "$CREATE_RELEASE_LOGIC"
  [ "$status" -eq 0 ]
  run cat "$GH_CALL_LOG"
  [[ "$output" != *"--draft"* ]]
  [[ "$output" != *"--prerelease"* ]]
}

@test "create release: overflow found attaches release-notes-full.md" {
  stub_gh
  export OVERFLOW_FOUND="true"
  export SBOM_FILENAME="bluefin.spdx.json"
  run bash -c "$CREATE_RELEASE_LOGIC"
  [ "$status" -eq 0 ]
  run cat "$GH_CALL_LOG"
  [[ "$output" == *"bluefin.spdx.json release-notes-full.md"* ]]
}

@test "create release: no overflow leaves release-notes-full.md off the asset list" {
  stub_gh
  export SBOM_FILENAME="bluefin.spdx.json"
  run bash -c "$CREATE_RELEASE_LOGIC"
  [ "$status" -eq 0 ]
  run cat "$GH_CALL_LOG"
  [[ "$output" != *"release-notes-full.md"* ]]
}
