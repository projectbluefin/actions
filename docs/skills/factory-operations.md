---
name: factory-operations
description: Production gate (2-human approval), promotion cadence and merge-queue contract, factory health monitor, and Renovate auto-merge.
metadata:
  type: reference
---

# Factory Operations Skill

Covers systems that keep the projectbluefin factory safe:

1. **Production gate** - machine-enforced 2-human approval before any build reaches `:stable`
2. **Promotion cadence** - per-repo schedule, `use_merge_queue` contract, and `run_e2e` rationale
3. **Factory health monitor** - scheduled pipeline health monitoring with automatic issue creation
4. **Renovate auto-merge** - automated dependency bump management

---

## 1. Production Gate (Track C-1)

### What it is

A GitHub Environment named `production` added to the promotion job in each image repo's release workflow. GitHub blocks the job until the required number of distinct human approvers click Approve in the Environments UI.

### Where it lives

| Repo | Workflow | Job |
|---|---|---|
| `projectbluefin/bluefin` | `weekly-testing-promotion.yml` | `promote` |
| `projectbluefin/dakota` | `weekly-testing-promotion.yml` | `promote` |
| `projectbluefin/bluefin-lts` | `scheduled-lts-release.yml` | `trigger-lts-builds` |

### Workflow snippet

```yaml
jobs:
  promote:
    runs-on: ubuntu-latest
    environment:
      name: production
      url: https://ghcr.io/projectbluefin/bluefin:stable
    steps:
      - # ... SHA-lock + verify-e2e + skopeo copy ...
```

### Manual GitHub UI setup (one-time per repo)

After the workflow change is merged:
1. Go to the repo → **Settings → Environments → New environment**
2. Name: `production`
3. Set **Required reviewers** - list the 4 maintainers (`castrojo`, `p5`, `m2Giles`, `tulilirockz`)
4. Set the **required count to 2** (two distinct approvals)
5. Restrict to the `main` branch

### Verification

- Trigger the promotion workflow via `workflow_dispatch`
- Confirm the job pauses with a yellow "Waiting for approval" status
- One reviewer approves → job stays paused
- Second reviewer approves → job runs
- Author approving their own dispatch is blocked (GitHub prevents self-approval when ≥1 review required)

### What it does NOT prevent

Repo admins can bypass Environment rules. All bypasses are permanently visible in:
- `gh api repos/<org>/<repo>/deployments` - every deployment record
- The Environment's deployment history page in GitHub UI

The protection is friction-ful for accidental/casual bypasses, not cryptographically airtight. This is the appropriate bar for a trusted team of 4.

---

## 2. Promotion Cadence and Merge Queue Contract

Each consumer repo promotes `:testing` → `:stable` (or `:lts`) via a thin caller to
`reusable-promote-squash.yml@v1`. The cadence and merge-queue behavior differ per repo — this
section is the canonical reference so edits to consumer `promote-testing-to-main.yml` preserve
the contract.

### Per-repo schedule and inputs

| Repo | Cron (UTC) | `use_merge_queue` | `run_e2e` | Notes |
|---|---|---|---|---|
| `projectbluefin/bluefin` | daily `0 23 * * *` | `true` (always) | `false` | also triggers on push to `testing`, `workflow_run` (Post-Testing E2E), and `pull_request_review` |
| `projectbluefin/bluefin-lts` | Tuesday `0 4 * * 2` | `false` | `false` | direct branch builds; no squash promotion PR |
| `projectbluefin/dakota` | Tuesday `0 4 * * 2` | conditional (see below) | `false` | e2e gate is at the environment approval level, not the PR gate |

### Conditional merge-queue enrollment (dakota pattern)

Dakota passes `use_merge_queue` as an expression rather than a constant:

```yaml
use_merge_queue: ${{ github.event_name == 'schedule' || github.event_name == 'workflow_dispatch' }}
```

This enrolls the PR in the merge queue **only when triggered by a scheduled run or manual dispatch**
(the weekly release path), not when triggered by a push to the source branch (routine refresh).
Enqueue on every push would cause the merge queue to process unnecessary entries.

### Why `use_merge_queue` matters

`enablePullRequestAutoMerge` (the GraphQL mutation for standard auto-merge) is blocked by GitHub
when the target branch has a merge queue ruleset enabled. Calling it silently fails.
`enqueuePullRequest` (the alternative used when `use_merge_queue: true`) places the PR directly
in the queue, where the queue runner merges it once all required checks pass.

**If you add a merge queue ruleset to a repo's target branch, set `use_merge_queue: true`
(or the conditional expression above if you want queue-only on weekly runs).**

### Why `run_e2e: false`

E2E evidence is gathered out-of-band by `post-testing-e2e.yml` (bluefin) or at the
`environment: production` approval gate level (dakota). The promotion PR gate runs cosign
signature verification only — it does not re-trigger E2E. Setting `run_e2e: true` at the
promotion step would duplicate the gate and create a dependency on testsuite availability
during the promotion window.

---

## 3. Factory Health Monitor

### What it is

A scheduled workflow (`actions/.github/workflows/factory-health.yml`) that checks the last 24 hours of
critical factory pipelines and opens an issue in `projectbluefin/common` when any monitored pipeline
falls below the success-rate threshold.

### Schedule

`cron: '0 */6 * * *'` - every 6 hours. Also triggerable via `workflow_dispatch`.

### Monitored pipelines

| Repo | Pipeline | Workflow queried |
|---|---|---|
| `projectbluefin/bluefin` | Build | `Testing Images` |
| `projectbluefin/bluefin` | E2E | `Nightly E2E` |
| `projectbluefin/bluefin` | Promote | `Promote testing to main` |
| `projectbluefin/bluefin-lts` | Build | `Build Bluefin LTS` |
| `projectbluefin/bluefin-lts` | E2E | `Post-Merge E2E - Testing Parity` |
| `projectbluefin/bluefin-lts` | Promote | `Promote testing to main` |
| `projectbluefin/dakota` | Build | `Build Bluefin dakota` |
| `projectbluefin/dakota` | Promote | `Publish Bluefin dakota` |
| `projectbluefin/common` | Build | `Build` |
| `projectbluefin/common` | Unit Tests | `Unit Tests` |

### Alerting behavior

- Success rate = `successful completed runs / completed non-skipped runs`
- Window = last 24 hours
- Threshold = 80%
- Open issues are deduplicated by repo + pipeline title prefix
- Issues are filed in `projectbluefin/common` with the labels that currently exist from:
  `priority/p0`, `area/ci`, `kind/bug`

### Authentication pattern

Use the workflow `github.token` for read-only `gh run list` calls against the public factory repos.
Generate a GitHub App token scoped to `projectbluefin/common` before creating issues there. This keeps
cross-repo issue writes explicit while avoiding broader write scopes for routine monitoring.

### Output

The workflow always prints a markdown summary table to stdout and `$GITHUB_STEP_SUMMARY`, even when no
issues are opened.

---

## 4. Renovate - Automated Dependency Maintenance

### What it does

Renovate runs as the MergeRaptors GitHub App and opens PRs to bump pinned action SHAs and digests. Qualifying PRs auto-merge when CI passes - no human review needed.

### Config

Two files co-exist:
- `.github/renovate.json5` - base org config (inherited from `projectbluefin/renovate-config`)
- `renovate.json` - repo-level overrides, including the `packageRules` automerge block

The effective automerge rule in `renovate.json`:

```json
{
  "packageRules": [
    {
      "description": "Automerge chore dep updates (digest, pin, patch, minor) when CI passes",
      "matchUpdateTypes": ["digest", "pin", "patch", "minor"],
      "automerge": true,
      "automergeType": "pr",
      "automergeStrategy": "squash"
    }
  ]
}
```

**What auto-merges:** SHA digest bumps, pin updates, patch and minor version bumps - when all CI checks pass. These are safe to auto-merge because they carry no behavior change.

**What never auto-merges:** Major version bumps and any PR that fails CI.

**Consumer-validation exemption:** Renovate PRs (author login ending in `[bot]` or starting with `app/`) are automatically exempt from the consumer PR + CI run evidence requirement, even when they touch action files. See `docs/skills/consumer-validation.md`.

### Validation workflow

`.github/workflows/validate-renovate.yml` runs `renovate-config-validator --strict` on PRs and pushes that touch either Renovate config file. Changes that fail validation are caught before merging.

### Auto-merge repo setting

The repository has `allow_auto_merge: true` enabled. Without this, GitHub ignores the `automerge` setting regardless of config.

### Relationship to `@v1`

Renovate keeps SHA pins current **for third-party actions in this repo**. Consumers don’t see the updates until a maintainer advances the `@v1` tag. See the `@v1` runbook in AGENTS.md for the exact commands.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Renovate PR won't auto-merge | `allow_auto_merge` disabled on repo | `gh api -X PATCH repos/projectbluefin/actions -f allow_auto_merge=true` |
| Renovate PR consumer-validation fails | Bot exemption not firing | Verify author login ends in `[bot]` or starts with `app/` - check `gh pr view NNN --json author` |
| Renovate PR has merge conflict | Another bump landed first; branches diverged | Locally checkout the branch, `git rebase origin/main`, force-push |
| Two Renovate PRs update the same action | Both opened before either merged | Close the older/lower version one; merge the newer |
| Dependency Dashboard (issue #42) shows PRs as "Open" | Renovate dashboard is eventually consistent - PRs may already be merged | Confirm with `gh pr view NNN --json mergedAt` before acting; the dashboard self-corrects on next Renovate run |
| Renovate warns: "Fallback to renovate.json as preset is deprecated" | Config file named `renovate.json` instead of `default.json` | Rename: `git mv renovate.json default.json` - content stays identical |

---

## 5. Promotion PR Format (Design C)

Every `testing → stable` promotion PR in bluefin and dakota uses a consistent
“Design C” body generated by `scripts/render_pr_body.py`.

### Title format

```
ci(promote): <primary-image> testing → stable YYYY-MM-DD
```

Examples: `ci(promote): bluefin testing → stable 2026-06-11`

### Body structure

```markdown
## 🦕 Bluefin testing → stable · 2026-06-11

> **12 days since the last stable release** · [tag ↗](release-url)
> Auto-maintained · Updated ISO-timestamp · [Run ↗](run-url)

<!-- gate-section-start -->
### Release checklist
**✅ All checks passed**
| Check | Status | Details |
|---|---|---|
| Digest resolution | ✅ passed | ... |
| Cosign signatures | ✅ passed | ... |
| E2E | ✅ passed | ... |
<!-- gate-section-end -->

### Variants being promoted
(variants table with digests when available)

### Changes since last stable
(commit count + collapsible commit log — squash workflow only)

## Desktop Screenshot

> [!CAUTION]
> **Auto-merge scheduled for Tuesday 04:00 UTC (bluefin/dakota) / Thursday 04:00 UTC (bluefin-lts).**
> To block this release: add the `do-not-merge` label to this PR before that time.
> Remove the label when the issue is resolved -- the next weekly window will pick it up automatically.

![bluefin desktop](https://projectbluefin.github.io/testsuite/screenshots/bluefin-smoke-latest.png)
```

The gate checklist starts with ⏳ placeholders written by the promote job,
then the gate job replaces only the `<!-- gate-section-start/end -->` block
with live ✅/❌ results via `scripts/render_gate_section.py`.

Promotion PRs must carry the screenshot + caution block in the **body**, not a
separate GitHub comment. If the PR is labelled `do-not-merge`, the reusable
workflow skips auto-merge / merge-queue enrollment until the label is removed.

### Scripts

| Script | Called by | Purpose |
|---|---|---|
| `scripts/render_pr_body.py` | promote job | Full PR body with ⏳ gate placeholders |
| `scripts/render_gate_section.py` | gate job | Targeted gate section replacement only |

### Consumer repo branch targets

| Repo | Workflow | Target branch for PRs |
|---|---|---|
| `projectbluefin/bluefin` | `reusable-promote-squash.yml` | `testing` |
| `projectbluefin/dakota` | `reusable-promote.yml` | `main` |
| `projectbluefin/bluefin-lts` | not yet adopted — see [bluefin-lts#172](https://github.com/projectbluefin/bluefin-lts/issues/172) | — |

**bluefin-lts** uses a different release model (weekly direct builds on `lts` branch, no promotion PR).
Tracked in bluefin-lts#172.

---

## 6. Promotion and sync-branches known patterns

### enqueuePullRequest vs enablePullRequestAutoMerge

For repos with a **merge queue** enabled, `enablePullRequestAutoMerge` is blocked by GitHub.
Use the `enqueuePullRequest` GraphQL mutation instead:

```bash
gh api graphql \
  -f query='mutation($id:ID!){enqueuePullRequest(input:{pullRequestId:$id}){mergeQueueEntry{id}}}' \
  -f id="$(gh pr view <PR> --json id -q .id)"
```

`reusable-promote-squash.yml` uses this pattern when enabling auto-merge on promotion PRs.

### E2E gate must use source_branch HEAD SHA — not a hardcoded ref

The promote-squash workflow queries the E2E gate against the `source_branch` HEAD SHA
(e.g. `testing` HEAD), **not** a hardcoded `main` or the caller's `github.ref`:

```bash
# Correct — lock to the branch that the E2E workflows ran against
SHA=$(gh api repos/$REPO/git/ref/heads/$E2E_HEAD_BRANCH --jq '.object.sha')
```

Using a hardcoded branch or `github.ref` can match a more-recent commit that hasn't had
E2E run yet, silently allowing un-tested code through the promotion gate.

### Force-push guard: skip when squash tree is unchanged

Before force-pushing the squash branch to an existing promotion PR, compare the squash tree
to the PR's current HEAD. If they match, skip the force-push entirely — force-pushing an
identical tree dismisses reviewers' approvals for no reason:

```bash
SQUASH_TREE=$(git rev-parse HEAD^{tree})
REMOTE_TREE=$(git ls-remote origin "refs/heads/$BRANCH" | cut -f1 | xargs git cat-file -p | grep tree | cut -d' ' -f2)
[ "$SQUASH_TREE" = "$REMOTE_TREE" ] && echo "no-op, skipping force-push"
```

### reusable-sync-branches: optional GH_TOKEN + force-reset for diverged branches

`reusable-sync-branches.yml` merges `source_branch` into `target_branch` after a promotion.
Two patterns to know:

**Protected branches:** The workflow accepts an optional `GH_TOKEN` secret from the caller.
When provided, it uses a GitHub App token to bypass protected-branch push rules. Without it,
`github.token` is used — which fails on protected branches.

**Diverged target:** If the target branch has commits not in source (e.g. direct CI fixes on
`main` while `testing` was being promoted), the workflow force-resets `target` to `source`
instead of attempting a merge. This is safe because:
- `main` only receives CI fixes that don't need cherry-picking
- A failed merge leaves the pipeline broken indefinitely
- Force-reset produces a clean, predictable state

---

## How the Systems Work Together

```
Factory health monitor runs every 6 hours
  └─▶ success rate < 80%
        ├── no open alert issue → opens issue in projectbluefin/common
        └── open alert issue exists → logs and skips duplicate creation

Renovate detects stale SHA pin
  └─▶ Opens bump PR
        ├── CI (actionlint) passes → auto-merges
        └── CI fails → stays open for human review

Batch of Renovate bumps land on main
  └─▶ Maintainer runs: git tag -f v1 origin/main && git push --force origin v1
        └─▶ All consumer repos pick up updated SHA pins on next workflow run
```

Renovate keeps pins fresh automatically; the factory health monitor surfaces failing pipelines quickly; and the production gate plus @v1 human authorization keep consumers safe.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Environment gate never appears | `production` Environment not configured in GitHub UI | Follow the Manual GitHub UI setup steps above |
| Both reviewers approved but job didn't start | GitHub Environments cache can take ~30s to register approvals | Wait 30s and refresh the Actions run page |
