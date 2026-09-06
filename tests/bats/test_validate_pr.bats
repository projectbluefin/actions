#!/usr/bin/env bats
# Tests for bootc-build/validate-pr/action.yml inline shell steps.
#
# validate-pr is a composite action; three of its steps carry real shell
# logic that has never been exercised by a test:
#
#   1. "Shellcheck system_files scripts"  — multi-pattern glob expansion of
#      inputs.system-files-shellcheck-glob, file-vs-directory filtering, and
#      the empty-match skip message.
#   2. "Validate desktop files"           — system_files/**/*.desktop discovery
#      and the "no files found" early exit.
#   3. "Check submodule drift"            — comma-separated path splitting,
#      space stripping, empty-entry skipping, and the aggregate exit status
#      when more than one submodule has drifted.
#
# The snippets below are copied verbatim from action.yml so this file breaks
# if the action's logic changes without the test being updated.

# ── Snippets copied from bootc-build/validate-pr/action.yml ───────────────────

SYSTEM_FILES_SHELLCHECK_SNIPPET='
set -euo pipefail
shopt -s globstar nullglob
files=()
# shellcheck disable=SC2086
for pattern in ${SHELLCHECK_GLOB}; do
  for f in $pattern; do
    [[ -f "$f" ]] && files+=("$f")
  done
done
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No system_files shell scripts found matching: ${SHELLCHECK_GLOB}"
else
  echo "Shellchecking ${#files[@]} system_files scripts..."
  shellcheck "${files[@]}"
fi
'

DESKTOP_VALIDATE_SNIPPET='
set -euo pipefail
shopt -s globstar nullglob
files=(system_files/**/*.desktop)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No .desktop files found — skipping"
  exit 0
fi
echo "Validating ${#files[@]} .desktop files..."
desktop-file-validate "${files[@]}"
'

SUBMODULE_DRIFT_SNIPPET='
set -euo pipefail
git submodule update --init --recursive
IFS='"'"','"'"' read -ra paths <<< "${SUBMODULE_PATHS}"
failed=0
for path in "${paths[@]}"; do
  path="${path// /}"
  [[ -z "$path" ]] && continue
  echo "Checking submodule drift: $path"
  if ! git diff --exit-code -- "$path"; then
    echo "ERROR: $path has been manually edited — changes must go upstream via a submodule PR"
    failed=1
  fi
done
exit "$failed"
'

setup() {
  TEST_TMP=$(mktemp -d)
  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"
  export WORKSPACE="${TEST_TMP}/workspace"
  mkdir -p "$WORKSPACE"
  cd "$WORKSPACE" || return 1
}

teardown() {
  cd / || true
  rm -rf "$TEST_TMP"
}

# Helper: record every argument a stubbed tool was invoked with.
make_recording_stub() {
  local name="$1" exit_code="${2:-0}"
  cat > "${MOCK_DIR}/${name}" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$@" >> "${TEST_TMP}/${name}.args"
exit ${exit_code}
EOF
  chmod +x "${MOCK_DIR}/${name}"
}

# Helper: arguments the stub was called with, one per line.
stub_args() {
  cat "${TEST_TMP}/$1.args" 2>/dev/null || true
}

stub_called() {
  [[ -f "${TEST_TMP}/$1.args" ]]
}

# ── Shellcheck system_files scripts ───────────────────────────────────────────

@test "system_files shellcheck: no matches prints skip message and does not run shellcheck" {
  make_recording_stub shellcheck
  export SHELLCHECK_GLOB='system_files/**/*.sh'
  run bash -c "$SYSTEM_FILES_SHELLCHECK_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No system_files shell scripts found matching: system_files/**/*.sh"* ]]
  ! stub_called shellcheck
}

@test "system_files shellcheck: matched scripts are passed to shellcheck" {
  make_recording_stub shellcheck
  mkdir -p system_files/usr/bin
  touch system_files/usr/bin/one.sh system_files/usr/bin/two.sh
  export SHELLCHECK_GLOB='system_files/**/*.sh'
  run bash -c "$SYSTEM_FILES_SHELLCHECK_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Shellchecking 2 system_files scripts..."* ]]
  [[ "$(stub_args shellcheck)" == *"system_files/usr/bin/one.sh"* ]]
  [[ "$(stub_args shellcheck)" == *"system_files/usr/bin/two.sh"* ]]
}

@test "system_files shellcheck: globstar recurses into nested directories" {
  make_recording_stub shellcheck
  mkdir -p system_files/a/b/c
  touch system_files/a/b/c/deep.sh
  export SHELLCHECK_GLOB='system_files/**/*.sh'
  run bash -c "$SYSTEM_FILES_SHELLCHECK_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$(stub_args shellcheck)" == *"system_files/a/b/c/deep.sh"* ]]
}

@test "system_files shellcheck: directories ending in .sh are filtered out" {
  make_recording_stub shellcheck
  mkdir -p system_files/usr
  mkdir -p system_files/usr/notascript.sh
  touch system_files/usr/real.sh
  export SHELLCHECK_GLOB='system_files/**/*.sh'
  run bash -c "$SYSTEM_FILES_SHELLCHECK_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Shellchecking 1 system_files scripts..."* ]]
  [[ "$(stub_args shellcheck)" != *"notascript.sh"* ]]
}

@test "system_files shellcheck: multiple whitespace-separated patterns are all expanded" {
  make_recording_stub shellcheck
  mkdir -p system_files/usr shared_files
  touch system_files/usr/a.sh shared_files/b.sh
  export SHELLCHECK_GLOB='system_files/**/*.sh shared_files/**/*.sh'
  run bash -c "$SYSTEM_FILES_SHELLCHECK_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Shellchecking 2 system_files scripts..."* ]]
  [[ "$(stub_args shellcheck)" == *"system_files/usr/a.sh"* ]]
  [[ "$(stub_args shellcheck)" == *"shared_files/b.sh"* ]]
}

@test "system_files shellcheck: one matching pattern is enough when another matches nothing" {
  make_recording_stub shellcheck
  mkdir -p system_files/usr
  touch system_files/usr/a.sh
  export SHELLCHECK_GLOB='system_files/**/*.sh does_not_exist/**/*.sh'
  run bash -c "$SYSTEM_FILES_SHELLCHECK_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Shellchecking 1 system_files scripts..."* ]]
}

@test "system_files shellcheck: a shellcheck violation fails the step" {
  make_recording_stub shellcheck 1
  mkdir -p system_files/usr
  touch system_files/usr/bad.sh
  export SHELLCHECK_GLOB='system_files/**/*.sh'
  run bash -c "$SYSTEM_FILES_SHELLCHECK_SNIPPET"
  [ "$status" -ne 0 ]
}

# KNOWN GAP (documented, not asserted as desirable): `for pattern in
# ${SHELLCHECK_GLOB}` is unquoted, so bash performs pathname expansion on
# SHELLCHECK_GLOB *before* the inner loop and then word-splits the resulting
# paths. A file under a directory containing a space becomes two bogus words
# ("system_files/my" and "dir/space.sh"), neither of which globs to anything
# under nullglob — so the script reports "no scripts found" and lints nothing.
# The step still exits 0, meaning the lint gate passes while silently skipping
# every script it was pointed at.
@test "system_files shellcheck: paths containing spaces are silently skipped (known gap)" {
  make_recording_stub shellcheck
  mkdir -p "system_files/my dir"
  touch "system_files/my dir/space.sh"
  export SHELLCHECK_GLOB='system_files/**/*.sh'
  run bash -c "$SYSTEM_FILES_SHELLCHECK_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No system_files shell scripts found matching"* ]]
  ! stub_called shellcheck
}

# Same root cause, seen from the other side: because SHELLCHECK_GLOB is itself
# glob-expanded by the outer loop, a directory whose name contains a space
# poisons matches for *unrelated* scripts in that expansion pass too.
@test "system_files shellcheck: a space-containing sibling path does not stop other scripts being linted" {
  make_recording_stub shellcheck
  mkdir -p "system_files/my dir" system_files/plain
  touch "system_files/my dir/space.sh" system_files/plain/ok.sh
  export SHELLCHECK_GLOB='system_files/**/*.sh'
  run bash -c "$SYSTEM_FILES_SHELLCHECK_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$(stub_args shellcheck)" == *"system_files/plain/ok.sh"* ]]
}

# ── Validate desktop files ────────────────────────────────────────────────────

@test "desktop validate: no .desktop files exits 0 with skip message" {
  make_recording_stub desktop-file-validate
  mkdir -p system_files/usr/share/applications
  run bash -c "$DESKTOP_VALIDATE_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No .desktop files found"* ]]
  ! stub_called desktop-file-validate
}

@test "desktop validate: missing system_files directory exits 0 rather than erroring" {
  make_recording_stub desktop-file-validate
  run bash -c "$DESKTOP_VALIDATE_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No .desktop files found"* ]]
}

@test "desktop validate: every discovered .desktop file is passed to the validator" {
  make_recording_stub desktop-file-validate
  mkdir -p system_files/usr/share/applications system_files/etc/skel
  touch system_files/usr/share/applications/one.desktop
  touch system_files/etc/skel/two.desktop
  run bash -c "$DESKTOP_VALIDATE_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Validating 2 .desktop files..."* ]]
  [[ "$(stub_args desktop-file-validate)" == *"system_files/usr/share/applications/one.desktop"* ]]
  [[ "$(stub_args desktop-file-validate)" == *"system_files/etc/skel/two.desktop"* ]]
}

@test "desktop validate: non-desktop files are not passed to the validator" {
  make_recording_stub desktop-file-validate
  mkdir -p system_files/usr/share/applications
  touch system_files/usr/share/applications/app.desktop
  touch system_files/usr/share/applications/README.md
  run bash -c "$DESKTOP_VALIDATE_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Validating 1 .desktop files..."* ]]
  [[ "$(stub_args desktop-file-validate)" != *"README.md"* ]]
}

@test "desktop validate: an invalid desktop file fails the step" {
  make_recording_stub desktop-file-validate 1
  mkdir -p system_files/usr/share/applications
  touch system_files/usr/share/applications/broken.desktop
  run bash -c "$DESKTOP_VALIDATE_SNIPPET"
  [ "$status" -ne 0 ]
}

# ── Check submodule drift ─────────────────────────────────────────────────────

# Helper: a git stub whose `diff --exit-code -- <path>` fails for the paths
# listed in DIRTY_PATHS and succeeds for everything else. `submodule` is a
# no-op so the snippet never touches a real repository.
make_git_stub() {
  cat > "${MOCK_DIR}/git" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "${TEST_TMP}/git.args"
case "\$1" in
  submodule) exit 0 ;;
  diff)
    target="\${!#}"
    for dirty in \${DIRTY_PATHS:-}; do
      if [[ "\$target" == "\$dirty" ]]; then
        echo "diff --git a/\$target b/\$target"
        exit 1
      fi
    done
    exit 0
    ;;
esac
exit 0
EOF
  chmod +x "${MOCK_DIR}/git"
}

@test "submodule drift: clean submodule exits 0" {
  make_git_stub
  export SUBMODULE_PATHS="aurorafin-shared"
  run bash -c "$SUBMODULE_DRIFT_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Checking submodule drift: aurorafin-shared"* ]]
  [[ "$output" != *"ERROR"* ]]
}

@test "submodule drift: submodules are initialised recursively before diffing" {
  make_git_stub
  export SUBMODULE_PATHS="aurorafin-shared"
  run bash -c "$SUBMODULE_DRIFT_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$(stub_args git)" == *"submodule update --init --recursive"* ]]
}

@test "submodule drift: an edited submodule fails with an actionable error" {
  make_git_stub
  export SUBMODULE_PATHS="aurorafin-shared"
  export DIRTY_PATHS="aurorafin-shared"
  run bash -c "$SUBMODULE_DRIFT_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"ERROR: aurorafin-shared has been manually edited"* ]]
  [[ "$output" == *"submodule PR"* ]]
}

@test "submodule drift: comma-separated list checks every path" {
  make_git_stub
  export SUBMODULE_PATHS="one,two,three"
  run bash -c "$SUBMODULE_DRIFT_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Checking submodule drift: one"* ]]
  [[ "$output" == *"Checking submodule drift: two"* ]]
  [[ "$output" == *"Checking submodule drift: three"* ]]
}

@test "submodule drift: surrounding spaces in the list are stripped" {
  make_git_stub
  export SUBMODULE_PATHS="one, two , three"
  export DIRTY_PATHS="two"
  run bash -c "$SUBMODULE_DRIFT_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Checking submodule drift: two"* ]]
  [[ "$output" == *"ERROR: two has been manually edited"* ]]
}

@test "submodule drift: empty list entries are skipped" {
  make_git_stub
  export SUBMODULE_PATHS="one,,two,"
  run bash -c "$SUBMODULE_DRIFT_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(grep -c 'Checking submodule drift:' <<< "$output")" -eq 2 ]
}

@test "submodule drift: a later clean path does not mask an earlier dirty one" {
  make_git_stub
  export SUBMODULE_PATHS="dirty,clean"
  export DIRTY_PATHS="dirty"
  run bash -c "$SUBMODULE_DRIFT_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"ERROR: dirty has been manually edited"* ]]
}

@test "submodule drift: every dirty path is reported, not just the first" {
  make_git_stub
  export SUBMODULE_PATHS="a,b"
  export DIRTY_PATHS="a b"
  run bash -c "$SUBMODULE_DRIFT_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"ERROR: a has been manually edited"* ]]
  [[ "$output" == *"ERROR: b has been manually edited"* ]]
}

@test "submodule drift: git diff is invoked with --exit-code and a -- path separator" {
  make_git_stub
  export SUBMODULE_PATHS="aurorafin-shared"
  run bash -c "$SUBMODULE_DRIFT_SNIPPET"
  [ "$status" -eq 0 ]
  [[ "$(stub_args git)" == *"diff --exit-code -- aurorafin-shared"* ]]
}

# ── Snippet drift guard ───────────────────────────────────────────────────────
#
# The snippets above are copies. If action.yml changes, these markers catch it
# so the copies get refreshed instead of silently testing dead logic.

@test "action.yml still contains the system_files shellcheck logic under test" {
  ACTION="${BATS_TEST_DIRNAME}/../../bootc-build/validate-pr/action.yml"
  [ -f "$ACTION" ]
  grep -q 'No system_files shell scripts found matching' "$ACTION"
  grep -q 'for pattern in \${SHELLCHECK_GLOB}' "$ACTION"
}

@test "action.yml still contains the desktop-file-validate logic under test" {
  ACTION="${BATS_TEST_DIRNAME}/../../bootc-build/validate-pr/action.yml"
  grep -q 'files=(system_files/\*\*/\*.desktop)' "$ACTION"
  grep -q 'desktop-file-validate' "$ACTION"
}

@test "action.yml still contains the submodule drift logic under test" {
  ACTION="${BATS_TEST_DIRNAME}/../../bootc-build/validate-pr/action.yml"
  grep -q 'has been manually edited' "$ACTION"
  grep -q 'git diff --exit-code' "$ACTION"
}
