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

## When to Use

- Adding or changing the caller-workflow size gate
- Editing `scripts/validate_thin_caller.py` or its tests
- Wiring the gate into CI, or changing `thin-caller-gate.yml`'s triggers or `paths:`
- A caller workflow trips the gate and you need to decide between extracting a
  reusable and adjusting the threshold

## When NOT to Use

- Auditing caller size in *consumer* repos — that is `factory-drift.yml`'s
  scheduled job, not this gate
- A workflow has no active `uses: projectbluefin/actions` reference; it is not a
  caller and this gate does not apply to it

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

## Core Process

1. Change `scripts/validate_thin_caller.py`? Update `tests/test_validate_thin_caller.py`
   and run `python3 scripts/validate_thin_caller.py --root .` to confirm exit 0.
2. Add the script or a workflow to CI? Trigger on `pull_request` + `push` to `main`
   and filter `paths:` to the touched surfaces (see `thin-caller-gate.yml`).
3. A real caller in a consumer repo exceeds the gate → fix by extracting a reusable,
   not by raising the threshold.

## Red Flags

- The gate flags a reusable workflow whose only `projectbluefin/actions`
  reference is commented-out header documentation — the comment-skip in
  `file_uses_projectbluefin` has regressed
- Someone proposes raising `--max-lines` to make a failing caller pass
- The gate is expected to catch an oversized caller living in a consumer repo;
  it only ever scans its own repo's `.github/workflows`
- `scripts/validate_thin_caller.py` changed but `tests/test_validate_thin_caller.py` did not

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The caller is only a bit over 50 lines, just bump the threshold." | The threshold is the contract. Extract the logic into a reusable in `projectbluefin/actions` instead. |
| "A commented-out `uses:` still counts as a caller." | It does not. Treating documentation as a caller was the original false-positive bug that flagged every reusable's header block. |
| "The weekly drift check already covers this." | `factory-drift.yml` is advisory and scheduled. This gate fails the build at PR time — that is the point of issue #411. |
| "This gate protects consumer repos too." | It runs per-repo against that repo's own `.github/workflows`. Consumer scraping stays with `factory-drift.yml`. |

## Verification

- [ ] `python3 scripts/validate_thin_caller.py --root .` exits 0
- [ ] `pytest tests/test_validate_thin_caller.py` passes
- [ ] A workflow whose only `projectbluefin/actions` reference is commented out is **not** reported as a caller
- [ ] `thin-caller-gate.yml` triggers on both `pull_request` and `push` to `main`, filtered to `.github/workflows/**` and `scripts/validate_thin_caller.py`
- [ ] Any caller that exceeds the threshold was fixed by extracting a reusable, not by raising `--max-lines`
