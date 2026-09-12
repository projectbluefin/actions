---
name: consumer-validation
description: Enforces the required consumer validation protocol before merging any action change. Use when modifying any action under bootc-build/ or reusable workflow under .github/workflows/, preparing a PR for review, running downstream integration tests in projectbluefin/bluefin, or resolving consumer validation CI check failures. Covers blast radius table, draft consumer PR procedure, automated CI check behavior, N/A rules, bot exemptions, and cross-fork approval flow.
metadata:
  type: reference
---

# Consumer Validation Protocol — projectbluefin/actions

Any change to this repo affects ALL consumers simultaneously via the `@v1` floating tag.

## Blast radius

| Consumer | Org | Notified? |
|---|---|---|
| `projectbluefin/bluefin` | projectbluefin | ✅ Direct access |
| `projectbluefin/bluefin-lts` | projectbluefin | ✅ Direct access |
| `ublue-os/aurora` | ublue-os (external) | ⚠️ No CI visibility |
| `ublue-os/bazzite` | ublue-os (external) | ⚠️ No CI visibility |

## Validation steps (required before merge)

1. **Open a draft consumer PR**: Create a draft PR in `projectbluefin/bluefin` (target: `testing`) using
   `@v1` references — no SHA pinning needed:
   ```yaml
   uses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1
   ```
   The PR only needs to exist and pass CI. It does not need to build the specific file you changed.
2. **Verify CI green**: Wait for the consumer PR's CI to pass completely.

   > **A draft consumer PR produces no CI run in `projectbluefin/bluefin`.** Its
   > `PR Validation — testsuite` workflow does not start while the PR is a draft,
   > so pushing more commits will not help — `gh api "repos/projectbluefin/bluefin/actions/runs?branch=<branch>"`
   > keeps returning `total_count: 0`, and there is no run ID to cite in step 3.
   > Mark the PR ready for review to get a run:
   >
   > ```bash
   > gh pr ready <number> --repo projectbluefin/bluefin
   > ```
   >
   > Say in the PR body that it exists solely for consumer validation and is not
   > for merge on its own. Close it once the actions PR has landed.
3. **Fill the PR template evidence fields** in this repo:
   - `Consumer PR: https://github.com/projectbluefin/<consumer>/pull/<number>`
   - `Consumer CI run: https://github.com/projectbluefin/<consumer>/actions/runs/<id>`
   - `Out-of-org consumer impact: <why aurora/bazzite are safe, or N/A>`
4. **Keep the checklist honest**: Check the three consumer-validation boxes only after the linked PR and run exist.
5. **Merge this actions PR**, then advance `@v1` to the new main HEAD (see the `@v1` runbook in AGENTS.md).
   Consumer repos pick up the change on their next workflow run — no further action needed.

## Automated PR check

`.github/workflows/consumer-validation.yml` makes the protocol harder to skip:

- It runs on PR open, sync, ready-for-review, and PR body edits.
- It only enforces the evidence fields when the PR changes `bootc-build/**/action.yml` or `.github/workflows/reusable-*.yml`.
- It fails if any required field is missing or in the wrong format.

**Bot/Renovate exemption:** PRs authored by a bot (login ending in `[bot]` or starting with `app/`, e.g. `renovate[bot]`, `mergeraptor[bot]`) are automatically exempt — they skip all three evidence checks. SHA pin bumps carry no behavior change and cannot provide consumer PR URLs.

**`no-floating-action-tags` pre-commit exemption scope:** The hook exempts `@v1` refs to
`projectbluefin/actions` only — not all `projectbluefin/*` repos. If a workflow in this repo
references another first-party repo (e.g. `projectbluefin/bonedigger`) with a floating tag,
the hook will flag it. Either SHA-pin the reference or add an explicit exemption to
`.pre-commit-config.yaml` with a comment explaining why.

**N/A rules — which fields accept it:**

| Field | Accepts "N/A"? | Requirement |
|---|---|---|
| `Consumer PR:` | ❌ No | Must be `https://github.com/projectbluefin/(bluefin\|bluefin-lts\|dakota)/pull/NNN` |
| `Consumer CI run:` | ❌ No | Must be `.../actions/runs/NNN` |
| `Out-of-org consumer impact:` | ✅ Yes | Any non-empty, non-`TODO`/`TBD` explanation (including "N/A — aurora/bazzite unaffected because...") |

Even for additive-only changes (new optional input with a safe default), you still need to open a draft consumer PR and get a CI run number. The consumer CI run URL is what proves the action was exercised in a real workflow.

**Cross-fork PRs:** External contributor PRs from forks need a maintainer to approve the pending workflow run before CI executes. Use:
```bash
gh api repos/projectbluefin/actions/actions/runs/<run-id>/approve -X POST
```

**After merging a fix to `consumer-validation.yml` itself:** `gh run rerun` re-executes the workflow from the HEAD branch's original commit — it ignores changes on `main`. To get a run using the updated workflow, push a new commit to the PR branch or admin-merge the PR directly.

Treat the check as evidence collection, not as a substitute for real validation. Fake links still violate policy and should be rejected in review.

## Consumer contract pre-commit check

`docs/consumer-contract.yml` is a machine-readable snapshot of all required inputs
consumed by external repos (`ublue-os/aurora`, `ublue-os/bazzite`) via `@v1`.

`scripts/check-consumer-contract.py` validates the snapshot against live `action.yml` files:

```bash
python3 scripts/check-consumer-contract.py --verbose
```

The `.pre-commit-config.yaml` `check-consumer-contract` hook runs this automatically
when `bootc-build/*/action.yml`, `reusable-*.yml`, or `consumer-contract.yml` change.

### When to update the snapshot

Update `docs/consumer-contract.yml` only when:
- An intentional breaking change is versioned (new `@v2` tag shipped), OR
- A new required input is added that consumers must explicitly adopt

**Never** remove a required input from the snapshot to silence the check — that defeats
the purpose. Instead, coordinate with aurora/bazzite maintainers and version the change.

## Out-of-org consumers

For `aurora` and `bazzite`, you cannot open PRs directly. Verify that your change does not break the Justfile contract (recipe signatures listed in `docs/skills/consumer-guide.md`) and summarize that reasoning in `Out-of-org consumer impact:`. If in doubt, ping `@castrojo` or `@hanthor`.

## Why this matters

The `@v1` tag is a floating pointer. A broken merge immediately breaks builds for ALL consumers with no rollback except a revert. The consumer validation step is the only gate.

## PR body format — critical pitfall

The consumer validation check searches for lines matching `^Consumer PR:` and `^Consumer CI run:` (colon immediately after the label). If your PR body uses **markdown headings** (`## Consumer PR`) instead of the **template format** (`Consumer PR: <URL>`), the check silently fails with "Missing 'Consumer PR:' line in the PR template".

**Wrong:**
```markdown
## Consumer PR
N/A — internal workflow, no consumer PR needed.
```

**Correct:**
```markdown
## Consumer validation

Consumer PR: https://github.com/projectbluefin/bluefin/pull/NNN
Consumer CI run: https://github.com/projectbluefin/bluefin/actions/runs/NNN
Out-of-org consumer impact: N/A — aurora/bazzite unaffected because ...
```

Even for internal-only workflows (like `reusable-renovate.yml`), the CI check still requires real URLs. Open a draft consumer PR in bluefin targeting `testing` — this exercises the actions repo at `@v1` and satisfies the check.

**How to create a consumer validation PR via API:**
```bash
# Create branch in bluefin from testing
gh api repos/projectbluefin/bluefin/git/refs --method POST \
  --field ref="refs/heads/consumer-validate/<name>" \
  --field sha="$(gh api repos/projectbluefin/bluefin/git/ref/heads/testing --jq '.object.sha')"
# Open draft PR targeting testing — workflow files already use @v1, so no content changes needed
gh pr create --repo projectbluefin/bluefin \
  --head consumer-validate/<name> --base testing \
  --title "ci: consumer validation for actions/<branch>" \
  --body "Consumer validation PR. No content changes — CI exercises @v1 references." \
  --draft
```

## Gotchas when writing the enforcement workflow itself

The `pat-ban.yml` enforcement workflow scans diff lines for `secrets.XXX` patterns. When that workflow was first authored, it failed its own CI check because:

1. A YAML comment in the workflow file said `# Find new secrets.XXX references` — the `secrets.XXX` literal matched the scanner's own grep pattern
2. Diff headers (`+++ b/file`) also appear as `+` lines and can carry false matches

**Fix applied:** The scanner filters `grep -v '^+++\|^+[[:space:]]*#'` to skip diff headers and YAML comment lines before extracting secret names. When writing or modifying enforcement checks that scan their own diffs, always add this filter.

**Authoring rule:** In any workflow file that discusses `secrets.NAME` in comments, write the name without the `secrets.` prefix to avoid triggering the scan. E.g., write `# GITHUB_TOKEN (built-in)` not `# secrets.GITHUB_TOKEN`.

---

## When to Use

Use this skill when:
- Preparing a PR that touches any file in `bootc-build/` or `.github/workflows/reusable-*.yml`.
- Creating a consumer validation PR in `projectbluefin/bluefin` (or other first-party consumer).
- Filling out the `Consumer PR`, `Consumer CI run`, and `Out-of-org consumer impact` fields in the actions PR template.
- Diagnosing failures in the `.github/workflows/consumer-validation.yml` CI check.
- Assessing blast radius across bluefin, bluefin-lts, aurora, and bazzite before landing changes.

## When NOT to Use

Do not use this skill to:
- Bypass consumer validation when changing action behavior, inputs, or workflow outputs.
- Validate pure docs-only changes or unit-test-only changes (these do not affect action execution, though CI checks evaluate path filters automatically).
- Configure upstream runner infrastructure or write new composite actions (see `composite-actions.md`).

## Core Process

1. **Assess blast radius**: Identify all consuming repositories (first-party and external) affected via the `@v1` floating tag.
2. **Open a consumer PR**: In `projectbluefin/bluefin` (or designated consumer), open a PR targeting the `testing` branch using `@v1` action references.
3. **Trigger and await CI**: Ensure the PR is ready for review (draft PRs in bluefin do not trigger CI workflows) and wait for a green CI run.
4. **Record evidence**: Obtain the full URLs for the consumer PR and consumer CI run.
5. **Populate actions PR template**: Insert the exact URLs into `Consumer PR:` and `Consumer CI run:`. Write a clear explanation in `Out-of-org consumer impact:` explaining why aurora and bazzite are safe.
6. **Verify CI passes**: Confirm that `.github/workflows/consumer-validation.yml` passes on your actions PR.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "My change is purely additive (new optional input), so no consumer PR is needed." | Additive changes can still break YAML parsing or introduce syntax bugs. CI check strictly enforces real URLs. |
| "Writing 'N/A' for Consumer PR because it is an internal workflow." | Only `Out-of-org consumer impact` accepts N/A with rationale; Consumer PR and CI run require valid URLs. |
| "The PR in bluefin is open as a draft; that's enough." | Draft PRs in bluefin do not trigger CI. The PR must be marked ready for review to generate a valid CI run. |
| "I'll merge the actions PR first, then test in bluefin." | That breaks `@v1` for all consumers simultaneously if anything is wrong. Consumer validation MUST precede merging. |

## Red Flags

- `N/A`, `TODO`, or `TBD` in `Consumer PR:` or `Consumer CI run:` fields in an action/workflow PR.
- Citing a bluefin branch without an actual PR or without an executed workflow run ID.
- Assuming an external consumer like aurora or bazzite will automatically report breaking changes before merge.
- Merging to `main` without verifying that the consumer PR's CI run completed successfully.

## Verification

- [ ] A valid consumer PR URL is present in `Consumer PR:` (`https://github.com/projectbluefin/.../pull/<id>`).
- [ ] A valid completed consumer workflow run URL is present in `Consumer CI run:` (`https://github.com/projectbluefin/.../actions/runs/<id>`).
- [ ] The referenced consumer CI run is green (all jobs passed).
- [ ] `Out-of-org consumer impact:` provides concrete rationale for why downstream external images will not break.
- [ ] The automated `consumer-validation.yml` check passes on the actions PR.
