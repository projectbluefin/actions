---
name: thin-caller-gate
description: Machine-enforced thin-caller size contract for caller workflows. Use when adding or changing the caller-workflow size gate, editing scripts/validate_thin_caller.py, or wiring the gate into CI.
metadata:
  type: reference
---

# Thin-Caller Gate

## Background

The factory "thin caller" design (issue #411) requires that caller workflows
which delegate to `projectbluefin/actions` reusables stay small (default
**50 effective lines**) and push all logic into reusables. Enforcement moved
from advisory (weekly `factory-drift.yml` drift check) to machine-enforced via
`scripts/validate_thin_caller.py` + a dedicated CI workflow.

## Files

| File | Role |
|---|---|
| `scripts/validate_thin_caller.py` | Finds `.github/workflows/*.yml{,a}` whose **active** (non-comment) content has a `uses: projectbluefin/actions/...` ref; fails if effective lines > `--max-lines`. |
| `.github/workflows/thin-caller-gate.yml` | CI job that runs the validator on `pull_request` and `push` to `main`, gated on `.github/workflows/**` and the script. |
| `tests/test_validate_thin_caller.py` | Unit tests for the validator. |

## Rules

- A **caller** is a workflow with an *active* `uses:` reference to
  `projectbluefin/actions`. Commented-out references (documentation / pinned-ref
  examples) are **not** callers and must not trip the gate — `file_uses_projectbluefin`
  skips lines whose first non-whitespace character is `#`.
- **Effective lines** = non-blank, non-comment lines (a `#`-first line is a comment).
- Threshold is 50. If a caller exceeds it, extract its logic into a reusable in
  `projectbluefin/actions` rather than growing the caller.

## Procedure

1. Change `scripts/validate_thin_caller.py`? Update `tests/test_validate_thin_caller.py`
   and run `python3 scripts/validate_thin_caller.py --root .` to confirm exit 0.
2. Add the script or a workflow to CI? Trigger on `pull_request` + `push` to `main`
   and filter `paths:` to the touched surfaces (see `thin-caller-gate.yml`).
3. A real caller in a consumer repo exceeds the gate → fix by extracting a reusable,
   not by raising the threshold.

## Pitfalls

- Do not count commented-out `uses:` as a caller — that was the original false-positive
  bug that flagged every reusable's header documentation.
- The gate runs per-repo against that repo's own `.github/workflows`; it does not
  scrape consumer repos (that is what `factory-drift.yml` still does on a schedule).
