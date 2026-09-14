#!/usr/bin/env bats
# Tests for bootc-build/apply-pkg-intervals inline shell logic.
#
# The shell logic lives inline in bootc-build/apply-pkg-intervals/action.yml
# in the "Apply update-interval xattrs" step.
#
# Covers:
#   - missing intervals file exits 0 with a warning annotation
#   - existing intervals file creates buildah container from SOURCE
#   - copies intervals file to /tmp/pkg-intervals.tsv in container
#   - runs container script to set user.update-interval on package files
#   - commits container back to SOURCE tag
#   - cleans up container on success or failure (trap cleanup EXIT)
#   - container script parses TSV, skips comments/empty lines, sets xattrs
#   - snippet drift guard against action.yml

APPLY_ORCHESTRATION_SNIPPET=$(cat <<'SNIP'
set -euo pipefail

if [[ ! -f "${INTERVALS_FILE}" ]]; then
  echo "::warning::apply-pkg-intervals: ${INTERVALS_FILE} not found — skipping"
  exit 0
fi

echo "::group::apply-pkg-intervals — setting user.update-interval xattrs from ${INTERVALS_FILE}"

CTR=$(sudo buildah from "${SOURCE}")

cleanup() { sudo buildah rm "${CTR}" 2>/dev/null || true; }
trap cleanup EXIT

sudo buildah copy "${CTR}" "${INTERVALS_FILE}" /tmp/pkg-intervals.tsv

sudo buildah run "${CTR}" -- bash -euo pipefail -c '
  total_pkgs=0; total_files=0; skipped=0
  while IFS='"'"'\t'"'"' read -r name interval _comment; do
    [[ "$name" =~ ^#.*$ || -z "$name" ]] && continue
    mapfile -t owned < <(rpm -ql "$name" 2>/dev/null || true)
    if [[ ${#owned[@]} -eq 0 ]]; then (( skipped++ )) || true; continue; fi
    for fpath in "${owned[@]}"; do
      [[ -e "$fpath" ]] || continue
      setfattr -n user.update-interval -v "$interval" "$fpath" 2>/dev/null || true
      (( total_files++ )) || true
    done
    (( total_pkgs++ )) || true
  done < /tmp/pkg-intervals.tsv
  rm -f /tmp/pkg-intervals.tsv
  echo "Set user.update-interval on ${total_files} files across ${total_pkgs} packages (${skipped} not installed)"
'

sudo buildah commit "${CTR}" "${SOURCE}"

echo "::endgroup::"
SNIP
)

setup() {
  TEST_TMP=$(mktemp -d)
  export TEST_TMP

  export STUB_BIN="${TEST_TMP}/bin"
  mkdir -p "$STUB_BIN"
  export CMD_LOG="${TEST_TMP}/cmd.log"
  : >"$CMD_LOG"

  cat >"${STUB_BIN}/sudo" <<'STUB'
#!/usr/bin/env bash
echo "sudo $*" >>"$CMD_LOG"
"$@"
STUB
  chmod +x "${STUB_BIN}/sudo"

  cat >"${STUB_BIN}/buildah" <<'STUB'
#!/usr/bin/env bash
echo "buildah $*" >>"$CMD_LOG"
case "${1:-}" in
  from)
    echo "ctr-mock-12345"
    ;;
  run)
    if [[ "${BUILDAH_RUN_FAIL:-0}" == "1" ]]; then
      echo "buildah run failed" >&2
      exit 1
    fi
    ;;
esac
exit 0
STUB
  chmod +x "${STUB_BIN}/buildah"

  export PATH="${STUB_BIN}:${PATH}"
  export SOURCE="localhost/bluefin:latest"
  export INTERVALS_FILE="${TEST_TMP}/files/pkg-intervals.tsv"
}

teardown() {
  rm -rf "$TEST_TMP"
}

# ── Host orchestration tests ──────────────────────────────────────────────────

@test "apply-pkg-intervals: missing intervals file emits warning and exits 0 cleanly" {
  export INTERVALS_FILE="${TEST_TMP}/nonexistent.tsv"
  run bash -c "$APPLY_ORCHESTRATION_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::warning::apply-pkg-intervals: "* ]]
  [[ "$output" == *"not found — skipping"* ]]

  run grep "buildah" "$CMD_LOG"
  [ "$status" -ne 0 ]
}

@test "apply-pkg-intervals: runs full buildah workflow when intervals file exists" {
  mkdir -p "$(dirname "$INTERVALS_FILE")"
  printf 'pkg-a\tfast\n' >"$INTERVALS_FILE"

  run bash -c "$APPLY_ORCHESTRATION_SNIPPET"
  [ "$status" -eq 0 ]

  run grep "buildah from localhost/bluefin:latest" "$CMD_LOG"
  [ "$status" -eq 0 ]

  run grep "buildah copy ctr-mock-12345 ${INTERVALS_FILE} /tmp/pkg-intervals.tsv" "$CMD_LOG"
  [ "$status" -eq 0 ]

  run grep "buildah run ctr-mock-12345" "$CMD_LOG"
  [ "$status" -eq 0 ]

  run grep "buildah commit ctr-mock-12345 localhost/bluefin:latest" "$CMD_LOG"
  [ "$status" -eq 0 ]

  run grep "buildah rm ctr-mock-12345" "$CMD_LOG"
  [ "$status" -eq 0 ]
}

@test "apply-pkg-intervals: cleans up container even if buildah run fails" {
  mkdir -p "$(dirname "$INTERVALS_FILE")"
  printf 'pkg-a\tfast\n' >"$INTERVALS_FILE"
  export BUILDAH_RUN_FAIL="1"

  run bash -c "$APPLY_ORCHESTRATION_SNIPPET"
  [ "$status" -eq 1 ]

  run grep "buildah rm ctr-mock-12345" "$CMD_LOG"
  [ "$status" -eq 0 ]
}

# ── Container inner loop logic tests ──────────────────────────────────────────

@test "apply-pkg-intervals: container inner loop processes packages and sets xattrs" {
  cat >"${STUB_BIN}/rpm" <<'STUB'
#!/usr/bin/env bash
pkg="${2:-}"
if [[ "$pkg" == "pkg-a" ]]; then
  echo "/usr/bin/pkg-a-bin"
elif [[ "$pkg" == "pkg-b" ]]; then
  echo "/usr/bin/pkg-b-bin"
else
  exit 1
fi
STUB
  chmod +x "${STUB_BIN}/rpm"

  cat >"${STUB_BIN}/setfattr" <<'STUB'
#!/usr/bin/env bash
echo "setfattr $*" >>"$CMD_LOG"
exit 0
STUB
  chmod +x "${STUB_BIN}/setfattr"

  mkdir -p "${TEST_TMP}/usr/bin"
  touch "${TEST_TMP}/usr/bin/pkg-a-bin"
  touch "${TEST_TMP}/usr/bin/pkg-b-bin"

  cat <<'EOF_INNER' >"${TEST_TMP}/test_inner.sh"
set -euo pipefail
total_pkgs=0; total_files=0; skipped=0
while IFS=$'\t' read -r name interval _comment; do
  [[ "$name" =~ ^#.*$ || -z "$name" ]] && continue
  mapfile -t owned < <(rpm -ql "$name" 2>/dev/null || true)
  if [[ ${#owned[@]} -eq 0 ]]; then (( skipped++ )) || true; continue; fi
  for fpath in "${owned[@]}"; do
    full_path="${TEST_TMP}${fpath}"
    [[ -e "$full_path" ]] || continue
    setfattr -n user.update-interval -v "$interval" "$full_path" 2>/dev/null || true
    (( total_files++ )) || true
  done
  (( total_pkgs++ )) || true
done < "$INPUT_TSV"
echo "Set user.update-interval on ${total_files} files across ${total_pkgs} packages (${skipped} not installed)"
EOF_INNER

  INPUT_TSV="${TEST_TMP}/intervals.tsv"
  printf '# Comment line\npkg-a\tslow\t# comment\npkg-uninstalled\tmedium\npkg-b\tfast\n\n# Another comment\n' >"$INPUT_TSV"
  export INPUT_TSV

  run bash "${TEST_TMP}/test_inner.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Set user.update-interval on 2 files across 2 packages (1 not installed)"* ]]

  run grep "setfattr -n user.update-interval -v slow ${TEST_TMP}/usr/bin/pkg-a-bin" "$CMD_LOG"
  [ "$status" -eq 0 ]
  run grep "setfattr -n user.update-interval -v fast ${TEST_TMP}/usr/bin/pkg-b-bin" "$CMD_LOG"
  [ "$status" -eq 0 ]
}

# ── Snippet drift guard ───────────────────────────────────────────────────────

@test "apply-pkg-intervals: action.yml still contains the interval application logic under test" {
  ACTION="${BATS_TEST_DIRNAME}/../../bootc-build/apply-pkg-intervals/action.yml"
  [ -f "$ACTION" ]
  grep -Fq 'apply-pkg-intervals: ${INTERVALS_FILE} not found — skipping' "$ACTION"
  grep -Fq 'sudo buildah copy "${CTR}" "${INTERVALS_FILE}" /tmp/pkg-intervals.tsv' "$ACTION"
  grep -Fq 'setfattr -n user.update-interval -v "$interval" "$fpath"' "$ACTION"
  grep -Fq 'sudo buildah commit "${CTR}" "${SOURCE}"' "$ACTION"
}
