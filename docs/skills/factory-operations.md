---
name: factory-operations
description: Production gate (2-human approval), skill-drift PR check, and scheduled skill audit - how the self-improving factory loop works and how to configure it. Use when configuring production approval gates, diagnosing skill-drift CI warnings, setting up the weekly skill audit, or managing Renovate auto-merge behavior.
metadata:
  type: reference
---

# Factory Operations Skill

Covers three interconnected systems that keep the projectbluefin factory safe and self-improving:

1. **Production gate** - machine-enforced 2-human approval before any build reaches `:stable`
2. **Skill-drift check** - PR-time warning when code changes without skill file updates
3. **Skill audit** - weekly scheduled freshness check with automatic issue creation

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

## 2. Skill-Drift PR Check (Track D-1)

### What it is

An informational CI check that warns when a PR changes code files without also touching skill/doc files. Always exits 0 - never blocks merging. Emits a `::warning::` annotation visible in the PR Checks tab.

### Architecture

Two files:

**`projectbluefin/actions/.github/workflows/skill-drift-check.yml`** - reusable workflow. Takes:
- `code-paths`: JSON array of globs for code files (e.g. `'[".github/workflows/**", "build_files/**"]'`)
- `skill-paths`: JSON array of globs for skill/doc files (e.g. `'["docs/skills/**", "AGENTS.md"]'`)

**Per-repo wrapper** (one per consumer repo, ~16 lines):

```yaml
# .github/workflows/skill-drift.yml
name: Skill Drift
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
  pull-requests: read
jobs:
  skill-drift:
    uses: projectbluefin/actions/.github/workflows/skill-drift-check.yml@v1
    with:
      code-paths: '[".github/workflows/**", "build_files/**", "Justfile"]'
      skill-paths: '["docs/skills/**", "docs/*.md", "AGENTS.md"]'
```

### Per-repo path configs

These are the committed reference configs currently deployed in each repo's `.github/workflows/skill-drift.yml` wrapper.

| Repo | `code-paths` | `skill-paths` |
|---|---|---|
| `projectbluefin/actions` | `'["bootc-build/**/action.yml", ".github/workflows/reusable-*.yml"]'` | `'["docs/skills/**"]'` |
| `projectbluefin/bluefin` | `'[".github/workflows/**", "build_files/**", "Justfile", "recipes/**"]'` | `'["docs/skills/**", "docs/*.md", "AGENTS.md"]'` |
| `projectbluefin/bluefin-lts` | `'[".github/workflows/**", "build_files/**", "Justfile"]'` | `'["docs/skills/**", "docs/*.md", "AGENTS.md"]'` |
| `projectbluefin/dakota` | `'[".github/workflows/**", "build_files/**", "Justfile", "elements/**"]'` | `'["docs/skills/**", "docs/*.md", "AGENTS.md"]'` |

### Bypass

Apply the label `skill-drift/no-update-needed` to the PR to silence the warning. This requires a CODEOWNER to apply it; the bypass is visible in the PR label history.

### Adding or widening a check

The check is intentionally narrow on `actions` (only `bootc-build/**/action.yml` and `reusable-*.yml`). If a PR type that causes drift is consistently slipping through, widen the `code-paths` glob in the per-repo wrapper and update this skill file in the same PR.

---

## 3. Skill Audit (Track D-2/D-3)

### What it is

A weekly scheduled workflow (`actions/.github/workflows/skill-audit.yml`) that:
- Compares each skill file's last-modified date to the last code commit in the areas it documents
- Opens a `skill-drift`-labelled issue when a skill is stale; adds a comment if an issue already exists (idempotent)
- Warns if a skill file is missing from the `docs/SKILL.md` routing table
- Warns if a skill file has a malformed front-matter block

### Schedule

`cron: '0 9 * * 1'` - Monday 09:00 UTC, before the Tuesday production window. Also triggerable via `workflow_dispatch`.

### Staleness heuristic

```
code_ts  = git log -1 --format=%ct -- bootc-build/ .github/workflows/reusable-*.yml
skill_ts = git log -1 --format=%ct -- docs/skills/<skill>.md
```

If `skill_ts < code_ts`: stale. The issue title encodes the number of days behind. On re-run, the existing issue gets a comment with the updated staleness count instead of a duplicate.

### Label setup

The workflow auto-creates the `skill-drift` label (color `e4e669`, description "Skill file is stale relative to code changes") if it doesn't exist. No manual setup required.

### What it does NOT audit

- Per-repo skill files in consumer repos (`bluefin/docs/skills/`, `bluefin-lts/docs/skills/`, `dakota/docs/skills/`) - those are out-of-scope for the `actions`-hosted audit. Consumer repos are responsible for their own skill freshness.
- Whether skill content is *correct* - only whether it was recently touched.

### Front-matter lint

Warns if a file in `docs/skills/*.md` does not start with `---`. Does not fail the job (all checks emit `::warning::`, audit exits 0 on lint violations too).

### Routing-table lint

Warns if any `docs/skills/*.md` file is not referenced by filename in `docs/SKILL.md`.

### Metrics

After all checks, the workflow logs a summary line:
```
==> Audit complete: N warning(s), N issue(s) opened
```

No `skill-metrics.json` artifact is produced currently (future enhancement if badge-based metrics are needed).

---

## 4. Factory Health Monitor

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

## 5. Renovate - Automated Dependency Maintenance

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

## 6. Promotion PR Format (Design C)

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

## 7. Promotion and sync-branches known patterns

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
        ├── CI (actionlint + skill-drift) passes → auto-merges
        └── CI fails → stays open for human review

PR opened (human or Renovate)
  └─▶ skill-drift-check.yml fires
        ├── code-paths changed + no skill-paths changed → ::warning:: annotation
        └── always exits 0 (never blocks)

Monday 09:00 UTC
  └─▶ skill-audit.yml fires
        ├── skill file older than latest code commit → open/update issue
        ├── skill file missing from SKILL.md → ::warning::
        └── skill file lacks front-matter → ::warning::

Human reviews warning / issue
  └─▶ Opens skill update PR
        └─▶ skill-drift-check passes cleanly (skill-paths changed)

Batch of Renovate bumps land on main
  └─▶ Maintainer runs: git tag -f v1 origin/main && git push --force origin v1
        └─▶ All consumer repos pick up updated SHA pins on next workflow run
```

Renovate keeps pins fresh automatically; the PR check and weekly audit keep knowledge current; the
factory health monitor surfaces failing pipelines quickly; and the production gate plus @v1 human
authorization keep consumers safe.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Skill-drift warning fires on a docs-only PR | `code-paths` glob is too broad | Narrow the glob or apply the bypass label |
| Audit opens duplicate issues | Issue title changed between runs, so existing search missed it | Check `gh issue list --label skill-drift --search <skill-name>` - if dupe, close the older one |
| Audit `code_ts` returns 0 | `bootc-build/` and reusable workflows have no git history at checkout depth | Ensure `fetch-depth: 0` in the audit workflow's checkout step |
| Environment gate never appears | `production` Environment not configured in GitHub UI | Follow the Manual GitHub UI setup steps above |
| Both reviewers approved but job didn't start | GitHub Environments cache can take ~30s to register approvals | Wait 30s and refresh the Actions run page |
