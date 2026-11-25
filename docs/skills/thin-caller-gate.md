---
name: thin-caller-gate
description: Enforce the thin-caller size contract on workflows that delegate to projectbluefin/actions reusables. Use when adding or reviewing a caller workflow, wiring the gate into a consumer repo's CI, or answering why a reusable caller is too large.
metadata:
  type: reference
---

# Thin-Caller Gate in the projectbluefin Actions Factory

## When to Use

Use when reviewing or adding a GitHub Actions workflow that `uses:` a
`projectbluefin/actions` **reusable workflow**, when wiring the gate into a
consumer repo's CI, or when a caller workflow is growing and someone asks
whether it should be extracted into a reusable instead.

## When NOT to Use

- Do not use it for workflows that call only third-party actions or
  `projectbluefin/actions` **composite actions** (`bootc-build/*`). A workflow
  that orchestrates composite actions as steps alongside other logic is not
  the "thin pointer to a reusable" pattern this gate targets — see
  `file_uses_projectbluefin` in `scripts/validate_thin_caller.py` for the
  detection scope.
- Do not use it to measure the reusable implementations themselves
  (`reusable-*.yml`, `bootc-build/*/action.yml`) — those are the extraction
  target, not callers.
- Do not treat a weekly drift warning as a pre-merge block; the gate is meant
  to fail the build, not just report it.

## Core Process

1. A caller workflow is any file under `.github/workflows/` with an active
   (non-comment) `uses:` line referencing a
   `projectbluefin/actions/.github/workflows/*` reusable.
2. Count its effective lines (non-blank, non-comment). The threshold is 50.
3. Run the canonical validator:

   ```bash
   python3 scripts/validate_thin_caller.py --max-lines 50 --root .
   ```

   Exit 0 passes; exit 1 lists each violating workflow and its line count.
4. On a violation, extract the logic into a reusable workflow in
   `projectbluefin/actions`, advance `@v1`, and keep the caller thin.

## Enforcing in a consumer repo (issue #546)

The provider repo (`projectbluefin/actions` itself) has no active caller
workflows, so running the gate here is vacuous — it can never catch the
violations it was written for (`promote-testing-to-main.yml` growing to 106
lines in bluefin was the motivating case, issue #411). The gate must run
*in the consumer repo's own PR checks* to block pre-merge.

`.github/workflows/reusable-thin-caller-gate.yml` publishes the check as a
`workflow_call` reusable. Consumer repos opt in with a **job** — reusable
workflows can only be invoked at `jobs.<id>.uses`, never as a step:

```yaml
jobs:
  thin-caller-gate:
    uses: projectbluefin/actions/.github/workflows/reusable-thin-caller-gate.yml@v1
```

The reusable sources the validator via explicit `workflow_call` inputs
(`actions_repository`, `actions_ref`), defaulting to `projectbluefin/actions`
at the commit the caller pinned this reusable to (`job.workflow_sha`),
instead of a value baked into the checkout step. A consumer that
later pins a `@v2` of this reusable inherits that version's own defaults;
nothing here silently drifts to whatever `@v1` happens to point at
independently of the ref the consumer actually invoked. Every consumer
enforces the identical rule from one source of truth. A caller workflow that
exceeds the 50-line threshold now fails a check before it reaches that
consumer's `main`/`testing` branch, instead of waiting for the weekly
`factory-drift.yml` backstop to report it after the fact.

To validate a fork or branch of this reusable itself (as opposed to a normal
consumer opt-in), override the inputs:

```yaml
jobs:
  thin-caller-gate:
    uses: <fork>/actions/.github/workflows/reusable-thin-caller-gate.yml@<sha>
    with:
      actions_repository: <fork>/actions
      actions_ref: <sha>
```

The weekly drift check remains the backstop for repos that have not adopted
the reusable yet. `factory-drift.yml`'s Check 4 runs this same canonical
`validate_thin_caller.py` against every fetched consumer workflow snapshot
(not just one hardcoded filename with a raw `wc -l` count), so the backstop
and the pre-merge gate agree on what counts as a violation.

**A backstop must not be able to pass silently.** Check 4 keys on the
validator's *exit code*, not on grepping its stdout for `  - ` lines, and it
treats four non-violation outcomes as drift items in their own right:

| Outcome | Drift item |
|---|---|
| The consumer's `.github/workflows` directory could not be listed (API error, repository renamed or archived); the fetch step writes a `.listing-failed` marker and Check 4 reads it before any count | `thin-caller-listing-failed` |
| No workflow files were fetched for a consumer (the loop `mkdir -p`s the directory first, so the validator sees an existing but empty tree, prints "nothing to check" and exits 0) | `thin-caller-snapshot-empty` |
| Fewer files landed than the consumer's directory listing advertised — a per-file fetch failed | `thin-caller-snapshot-incomplete` |
| Validator exits non-zero without listing violations (traceback, bad arguments) | `thin-caller-gate-error` |

All four report "this consumer was not actually checked" instead of the
clean pass that grepping stdout would have produced. If you add a check to
this workflow, follow the same rule: absence of a violation string is not
evidence of compliance.

Two details in the fetch step exist to make that true, and should not be
"simplified" away:

- The consumer's directory **listing** is tested directly (`if ! wf_list=$(gh
  api ...)`), and a failure is recorded as that consumer's own drift item
  before the loop moves to the next consumer. Piping it into a `while read`
  loop would turn a failed listing into an empty snapshot, quieter and worse;
  letting it abort the whole step under `set -e` would skip every check for
  every other consumer that week, which is quieter still. A consumer that
  lists successfully but advertises zero workflow files is skipped without a
  drift item: there is nothing for the gate to check.
- A failed **per-file** fetch is deleted rather than left in place. The `>`
  redirect creates the file before `gh api` runs, so a failure leaves a
  0-byte stub, and a stub counts as a fetched workflow to any later `find`.
  That is how a snapshot missing the one oversized caller would read as
  compliant. Check 4 then counts **every** file that is present — including a
  legitimately empty one — and compares the total against the advertised
  count. Do not add a `-size +0` filter here: an empty workflow file that
  fetched successfully is advertised *and* present, so excluding it would make
  advertised > landed forever and raise a `thin-caller-snapshot-incomplete`
  item that can never be cleared. The stub removal above, not a size filter,
  is what keeps a failed fetch visible
  (`tests/test_factory_drift_thin_caller_check.py`,
  `test_failed_fetch_stub_is_removed_and_empty_files_still_count`).

## Common Rationalizations

- "It's only a few lines over." — drift is cumulative; a 55-line caller today
  is a 120-line monolith before anyone notices (the original `promote
  -testing-to-main.yml`).
- "The weekly drift check will catch it." — that is the post-merge-detection
  problem #411 was filed about. Pre-merge is the point.
- "The caller is large because the reusable is incomplete." — that is a signal
  to grow the reusable, not to excuse the caller.
- "Our workflow calls a composite action, not a reusable, so it's fine to be
  long." — correct, and intentional: the gate only flags
  `.github/workflows/*` delegation. Composite-action orchestration (e.g.
  bluefin's `pr-validation.yml` calling `bootc-build/validate-pr`) is out of
  scope by design.

## Red Flags

- A caller workflow that reads like a job definition rather than a pointer.
- New `uses: projectbluefin/actions/.github/workflows/...` lines added to an
  already-thick caller.
- A consumer repo that has not opted into `reusable-thin-caller-gate.yml`
  while siblings have — it is drifting from the contract.
- Copying the opt-in snippet as a step (`- uses: ...`) instead of a job —
  GitHub Actions rejects `workflow_call` reusables used at step level, so the
  gate silently never runs.

## Verification

- `python3 scripts/validate_thin_caller.py --max-lines 50 --root .` exits 0.
- `pytest tests/` passes; the reusable's structure, job-level opt-in example,
  and configurable script source are covered by
  `tests/test_reusable_thin_caller_gate.py`; the comment-skip /
  composite-action-exclusion cases are covered by
  `tests/test_validate_thin_caller.py`; and the `factory-drift.yml` Check 4
  backstop (effective-line counting, not raw `wc -l`) is covered by
  `tests/test_factory_drift_thin_caller_check.py`.
- `.github/workflows/actionlint.yml` lints the reusable workflow on every PR.
