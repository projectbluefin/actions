---
name: factory-operations
description: Production gate (2-human approval), skill-drift PR check, and scheduled skill audit — how the self-improving factory loop works and how to configure it.
metadata:
  type: reference
---

# Factory Operations Skill

Covers three interconnected systems that keep the projectbluefin factory safe and self-improving:

1. **Production gate** — machine-enforced 2-human approval before any build reaches `:stable`
2. **Skill-drift check** — PR-time warning when code changes without skill file updates
3. **Skill audit** — weekly scheduled freshness check with automatic issue creation

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
3. Set **Required reviewers** — list the 4 maintainers (`castrojo`, `p5`, `m2Giles`, `tulilirockz`)
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
- `gh api repos/<org>/<repo>/deployments` — every deployment record
- The Environment's deployment history page in GitHub UI

The protection is friction-ful for accidental/casual bypasses, not cryptographically airtight. This is the appropriate bar for a trusted team of 4.

---

## 2. Skill-Drift PR Check (Track D-1)

### What it is

An informational CI check that warns when a PR changes code files without also touching skill/doc files. Always exits 0 — never blocks merging. Emits a `::warning::` annotation visible in the PR Checks tab.

### Architecture

Two files:

**`projectbluefin/actions/.github/workflows/skill-drift-check.yml`** — reusable workflow. Takes:
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
| `projectbluefin/actions` | `'["bootc-build/**/action.yml", ".github/workflows/reusable-*.yml", ".github/workflows/upgrade-*.yml"]'` | `'["docs/skills/**"]'` |
| `projectbluefin/bluefin` | `'[".github/workflows/**", "build_files/**", "Justfile", "recipes/**"]'` | `'["docs/skills/**", "docs/*.md", "AGENTS.md"]'` |
| `projectbluefin/bluefin-lts` | `'[".github/workflows/**", "build_files/**", "Justfile"]'` | `'["docs/skills/**", "docs/*.md", "AGENTS.md"]'` |
| `projectbluefin/dakota` | `'[".github/workflows/**", "build_files/**", "Justfile", "elements/**"]'` | `'["docs/skills/**", "docs/*.md", "AGENTS.md"]'` |

### Current consumer deployment status

The per-repo wrappers are no longer pending: all three consumer PRs merged on 2026-06-02, and the default branches now call `projectbluefin/actions/.github/workflows/skill-drift-check.yml@v1`.

| Repo | PR | Branch | Status |
|---|---|---|---|
| `projectbluefin/bluefin` | [#239](https://github.com/projectbluefin/bluefin/pull/239) | `feat/skill-drift-wrapper` | Merged / deployed |
| `projectbluefin/bluefin-lts` | [#24](https://github.com/projectbluefin/bluefin-lts/pull/24) | `feat/skill-drift-wrapper` | Merged / deployed |
| `projectbluefin/dakota` | [#660](https://github.com/projectbluefin/dakota/pull/660) | `feat/skill-drift-wrapper` | Merged / deployed |

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

`cron: '0 9 * * 1'` — Monday 09:00 UTC, before the Tuesday production window. Also triggerable via `workflow_dispatch`.

### Staleness heuristic

```
code_ts  = git log -1 --format=%ct -- bootc-build/ .github/workflows/reusable-*.yml
skill_ts = git log -1 --format=%ct -- docs/skills/<skill>.md
```

If `skill_ts < code_ts`: stale. The issue title encodes the number of days behind. On re-run, the existing issue gets a comment with the updated staleness count instead of a duplicate.

### Label setup

The workflow auto-creates the `skill-drift` label (color `e4e669`, description "Skill file is stale relative to code changes") if it doesn't exist. No manual setup required.

### What it does NOT audit

- Per-repo skill files in consumer repos (`bluefin/docs/skills/`, `bluefin-lts/docs/skills/`, `dakota/docs/skills/`) — those are out-of-scope for the `actions`-hosted audit. Consumer repos are responsible for their own skill freshness.
- Whether skill content is *correct* — only whether it was recently touched.

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

## How the Three Systems Work Together

```
PR opened
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
```

The PR check surfaces drift in real time; the audit catches anything that slips through and accumulates between PRs.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Skill-drift warning fires on a docs-only PR | `code-paths` glob is too broad | Narrow the glob or apply the bypass label |
| Audit opens duplicate issues | Issue title changed between runs, so existing search missed it | Check `gh issue list --label skill-drift --search <skill-name>` — if dupe, close the older one |
| Audit `code_ts` returns 0 | `bootc-build/` and reusable workflows have no git history at checkout depth | Ensure `fetch-depth: 0` in the audit workflow's checkout step |
| Environment gate never appears | `production` Environment not configured in GitHub UI | Follow the Manual GitHub UI setup steps above |
| Both reviewers approved but job didn't start | GitHub Environments cache can take ~30s to register approvals | Wait 30s and refresh the Actions run page |
