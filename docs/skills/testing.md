---
description: pytest setup, coverage baseline, and regression gate for the Python scripts in this repo. Use when modifying the unit-tests workflow, adding tests, or changing the coverage threshold.
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

Coverage gate: `--cov-fail-under=75`

### Shell scripts (bats)

| Script | Test file |
|---|---|
| `bootc-build/generate-tags/generate_tags.sh` | `tests/bats/test_generate_tags.bats` |
| `actions/retry/retry.sh` | `tests/bats/test_retry.bats` |
| `actions/check-token-health/check_token_health.sh` | `tests/bats/test_check_token_health.bats` |
| `scripts/resolve_digests.sh` | `tests/bats/test_resolve_digests.bats` |
| `scripts/verify_signatures.sh` | `tests/bats/test_verify_signatures.bats` |

The bats suite is run as a separate job in `unit-tests.yml` (see `bats/` job). Run locally:

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

Do not use `__wrapped__` introspection — it only applies to `functools.wraps`-decorated functions
and silently has no effect on plain functions.

## requirements-test.txt

```
pytest>=8.0
pytest-cov>=4.0
pyyaml>=6.0
```

`pytest-cov` ships as a pytest plugin — no extra import needed in test files.
