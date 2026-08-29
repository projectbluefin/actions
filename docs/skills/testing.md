---
description: pytest setup, coverage baseline, and regression gate for the Python scripts in this repo. Use when modifying the unit-tests workflow, adding tests, changing the coverage threshold, or testing shell logic embedded in actions.
metadata:
  type: reference
---

# Testing — Python Unit Tests

## Scope

The `unit-tests.yml` workflow covers two test suites:

### Python (pytest)

| Directory | Scripts |
|---|---|
| `bootc-build/create-release/scripts/` | `render_card.py`, `render_notes.py`, `sbom_diff.py` |
| `bootc-build/chunka/` | `inject-xattrs.py` |
| `scripts/` | `check-consumer-contract.py`, `monitor_pipeline.py`, `render_gate_section.py`, `render_pr_body.py` |

All directories are registered in `tests/conftest.py` via `sys.path.insert` so test files can
import scripts directly without per-file path manipulation.

### Path precedence rule for duplicate script names

Some `scripts/*.py` modules are duplicated under `.github/actions/*` so composite actions can run
them via `GITHUB_ACTION_PATH`. If both directories are added to `sys.path`, insertion order decides
which copy gets imported.

- Add `scripts/` before `.github/actions/*` when coverage should be attributed to shipped wrappers.
- For regression tests that must target a specific file, prefer `importlib.util.spec_from_file_location`
  with an explicit path to avoid accidental shadowing from `sys.path` order.

Coverage gate: `--cov-fail-under=75`

### Shell scripts (bats)

| Script | Test file |
|---|---|
| `bootc-build/generate-tags/generate_tags.sh` | `tests/bats/test_generate_tags.bats` |
| `actions/retry/retry.sh` | `tests/bats/test_retry.bats` |
| `actions/check-token-health/check_token_health.sh` | `tests/bats/test_check_token_health.bats` |
| `scripts/resolve_digests.sh` | `tests/bats/test_resolve_digests.bats` (10 tests) |
| `scripts/verify_signatures.sh` | `tests/bats/test_verify_signatures.bats` (15 tests) |
| `scripts/release_gate.sh` | `tests/bats/test_release_gate.bats` |
| `detect-changes` image_flavors shell logic | `tests/bats/test_detect_changes.bats` (8 tests) |
| `push-image` push/retry/alias shell logic | `tests/bats/test_push_image.bats` (16 tests) |
| `sign-and-publish` keyless/key validation + SBOM attach/cache/path guards | `tests/bats/test_sign_and_publish.bats` (19 tests) |
| `setup-runner` native-overlay setup | `tests/bats/test_setup_runner.bats` (9 tests) |

The bats suite runs in the `bats` job in `unit-tests.yml`. Run locally:

```bash
bats tests/bats/test_resolve_digests.bats
bats tests/bats/test_verify_signatures.bats
# or all at once:
bats tests/bats/
```

## Running tests locally

```bash
cd ~/src/actions
python -m pytest tests/ -v --tb=short \
  --ignore=tests/bats \
  --cov=bootc-build/chunka \
  --cov=bootc-build/create-release/scripts \
  --cov=scripts \
  --cov-report=term-missing \
  --cov-fail-under=75
```

## Raising the coverage threshold

1. Add tests in `tests/` for the uncovered paths
2. Run locally and confirm the new total
3. Update `--cov-fail-under=<new_value>` in `.github/workflows/unit-tests.yml`
4. Set the threshold to the actual measured value — never to a round number that isn't yet reached

**Do not set `--cov-fail-under` above the measured total** — it will immediately fail CI on the
next run and block every PR.

## Bats test patterns for shell scripts

### Mock external binaries via PATH injection

Prepend a temp `bin/` dir to PATH in `setup()` and write mock scripts there. This intercepts
`skopeo`, `cosign`, `curl`, etc. without system modification:

```bash
setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"
  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"
}

make_skopeo_success() {
  local digest="${1:-sha256:abc123}"
  cat > "${MOCK_DIR}/skopeo" <<EOF
#!/usr/bin/env bash
echo "${digest}"
EOF
  chmod +x "${MOCK_DIR}/skopeo"
}
```

### Heredoc quoting rule for mocks with dynamic paths

- **Unquoted** `<<EOF` — `${VAR}` in the heredoc expands at *write-time* (when the test creates
  the mock file). Use for file paths determined in the test (e.g. `${CALL_COUNT_FILE}`).
- **Quoted** `<<'EOF'` — everything is literal. Use for self-contained mocks where `$1`, `$2`,
  etc. should be evaluated at *run-time* by the mock script.

Mixing these incorrectly is the most common source of flaky bats mocks.

### Scripts that exit 0 on partial failure

Some scripts (e.g. `resolve_digests.sh`) always exit 0 and use `GITHUB_OUTPUT` to communicate
pass/fail. Do not assert `$status` for the pass/fail signal — assert the output variable:

```bash
# Wrong — exits 0 even when skopeo fails
[ "$status" -ne 0 ]

# Correct
[ "$(get_output ok)" = "false" ]
```

This is by design: GitHub Actions steps exit-gate on non-zero, but release-gate scripts need
to continue past individual failures to collect all results before deciding.

### Reading GITHUB_OUTPUT in bats

Add a helper to extract named values:

```bash
get_output() {
  local key="$1"
  grep "^${key}=" "$GITHUB_OUTPUT" | head -1 | cut -d= -f2-
}
```

For multiline values written with `<<EOF` delimiters, read the raw file and use `==` glob
matching instead:

```bash
[[ "$(<"$GITHUB_OUTPUT")" == *"bluefin|sha256:deadbeef"* ]]
```

### Testing shell logic embedded in action YAML

Composite action steps often have non-trivial shell logic inline in `action.yml` with no
corresponding standalone script file. The canonical approach:

1. **Capture the snippet verbatim** in a bats variable — this serves as a change detector:
   any edit to the action that alters testable behavior must update the test.

```bash
# In the bats file, at the top:
PUSH_LOGIC='
set -euo pipefail
...
# exact shell from action.yml run: block
'
```

2. **Run it with `bash -c`** in each test, setting env vars to simulate inputs:

```bash
@test "empty TAGS exits with error" {
  export TAGS=""
  run bash -c "$PUSH_LOGIC"
  [ "$status" -ne 0 ]
  [[ "$output" == *"At least one tag"* ]]
}
```

3. **Mock external binaries** via `PATH` injection (see "Mock external binaries" above).

4. **For best-effort commands (`... || true`)**, assert they stay non-fatal even when the mocked
   command fails, and add a companion test that verifies the command still executes with expected
   arguments. This catches accidental removal of `|| true` without turning permissive steps into
   silent no-ops.

**When the action has `sudo` calls:** add a pass-through `sudo` mock so tests run without
privilege. The mock just calls `"$@"`, then mock the real tool (`buildah`, `podman`) separately.

**Quoting pitfall:** embedding single-quoted shell inside a double-quoted heredoc requires
escaping with `'"'"'`. Use `'"'"'` to produce a literal `'` inside the shell snippet string:

```bash
# Produces: echo 'image_flavors=["main"]' >> "$GITHUB_OUTPUT"
SNIPPET='echo '"'"'image_flavors=["main"]'"'"' >> "$GITHUB_OUTPUT"'
```

Alternatively, assign the snippet via a POSIX `$(cat <<'EOF'...EOF)` block in `setup()`
if the quoting becomes unmanageable.

## Adding a new script

When a new Python script is added to any covered directory:

1. Add a corresponding `tests/test_<scriptname>.py`
2. Verify the new file appears in the coverage report (`--cov` paths are directory-level)
3. Re-measure total coverage — if it dropped, add tests to compensate before raising a PR

### Hyphenated filenames (e.g. `inject-xattrs.py`)

Python cannot `import inject-xattrs` directly. Use `importlib`:

```python
import importlib
inject_xattrs = importlib.import_module("inject-xattrs")
```

Register the script's directory in `tests/conftest.py` (preferred) rather than inline in the
test file — keeps the path boilerplate in one place for all current and future tests in that
directory.

### Calling `main()` in tests

For scripts that read `sys.argv`, patch argv rather than calling main with arguments:

```python
def _call_main(module, *args):
    orig = sys.argv
    try:
        sys.argv = ["script-name"] + list(args)
        return module.main()
    finally:
        sys.argv = orig
```

For entrypoint coverage, also exercise the module as a script with `runpy.run_path(..., run_name="__main__")` and assert `SystemExit` for CLI-style exits. This covers the `if __name__ == "__main__"` guard without needing a full end-to-end invocation:

```python
import runpy
import sys

orig = sys.argv
try:
    sys.argv = ["script-name", "--help"]
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path("/path/to/script.py", run_name="__main__")
    assert excinfo.value.code == 0
finally:
    sys.argv = orig
```

Do not use `__wrapped__` introspection — it only applies to `functools.wraps`-decorated functions
and silently has no effect on plain functions.

## requirements-test.txt

```
pytest>=8.0
pytest-cov>=4.0
pyyaml>=6.0
```

`pytest-cov` ships as a pytest plugin — no extra import needed in test files.

## When to Use

Use this skill when changing Python scripts, shell logic in actions, unit-test workflows, test
coverage, or mocks for external commands.

## When NOT to Use

Do not use this skill as proof of end-to-end consumer or QEMU behavior; those require workflow
and environment checks described by their respective runbooks.

## Core Process

1. Locate shipped entry point and its existing test or coverage path.
2. Add focused regression coverage for changed branches and preserve exact embedded shell when
   testing action YAML.
3. Mock external commands through a temporary PATH and isolate filesystem and environment state.
4. Run smallest relevant pytest or bats selector, then repository gate when shared test
   infrastructure or coverage changed.

## Common Rationalizations

- "The wrapper is covered." Confirm coverage targets the file CI actually executes, not a
  duplicate module selected by `sys.path`.
- "The command failed, so the test passed." Assert output variables when scripts intentionally
  return zero after partial failures.
- "A broad mock is simpler." Broad mocks hide argument and ordering regressions; assert calls.

## Red Flags

- Tests invoking real host `rpm`, `podman`, `buildah`, `skopeo`, or `cosign`.
- Coverage thresholds raised above the measured total.
- Shell snippets copied loosely instead of captured from the action definition.
- Tests depending on current working directory, host privileges, or persistent environment state.

## Verification

- [ ] Changed entry points and failure branches have focused tests.
- [ ] External tools and privileged calls are isolated with PATH mocks.
- [ ] Relevant pytest/bats command passes with configured coverage gate.
- [ ] Tests fail when guarded behavior is intentionally reverted.
