---
description: pytest setup, coverage baseline, and regression gate for the Python scripts in this repo. Use when modifying the unit-tests workflow, adding tests, or changing the coverage threshold.
---

# Testing — Python Unit Tests

## Scope

The `unit-tests.yml` workflow covers Python scripts in these directories:

| Directory | Scripts |
|---|---|
| `bootc-build/create-release/scripts/` | `render_card.py`, `render_notes.py`, `sbom_diff.py` |
| `bootc-build/chunka/` | `inject-xattrs.py` |
| `scripts/` | `check-consumer-contract.py` |

All directories are registered in `tests/conftest.py` via `sys.path.insert` so test files can
import scripts directly without per-file path manipulation.

## Coverage baseline (95 tests, 84% total)

| Module | Coverage | Uncovered lines |
|---|---|---|
| `render_card.py` | 55% | 323–337, 343–385, 389 (CLI entrypoint / `main()`) |
| `render_notes.py` | 52% | 41–44, 52–63, 69–70, 114–117, 308–365, 369 (CLI entrypoint / `main()`) |
| `sbom_diff.py` | 70% | 93, 125, 132, 184–234, 238 |
| `check-consumer-contract.py` | 62% | 20–22, 60–62, 73, 96–135, 139 |
| `inject-xattrs.py` | 97% | 64 (`__main__` guard — expected) |
| **TOTAL** | **84%** | — |

The gate is set at `--cov-fail-under=60`. The 80% target requires tests for the `main()` CLI
entrypoints in `render_card.py`, `render_notes.py`, and `sbom_diff.py` — those paths parse
`sys.argv` and write to disk/stdout, so they need `subprocess` or `monkeypatch` to cover.

## Running tests locally

```bash
cd ~/src/actions
python -m pytest tests/ -v --tb=short \
  --cov=bootc-build/create-release/scripts \
  --cov=scripts \
  --cov-report=term-missing \
  --cov-fail-under=60
```

## Raising the coverage threshold

1. Add tests in `tests/` for the uncovered paths
2. Run locally and confirm the new total
3. Update `--cov-fail-under=<new_value>` in `.github/workflows/unit-tests.yml`
4. Set the threshold to the actual measured value — never to a round number that isn't yet reached

**Do not set `--cov-fail-under` above the measured total** — it will immediately fail CI on the
next run and block every PR.

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
