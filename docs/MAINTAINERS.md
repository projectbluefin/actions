# Maintainer Guide — projectbluefin/actions

This guide is written for human maintainers. Agents have `AGENTS.md`; this page explains your role in the loop.

## What this repo is

Shared composite GitHub Actions consumed by bluefin, aurora, bazzite, and bluefin-lts via `projectbluefin/actions/bootc-build/<name>@v1`. Four maintainers: `castrojo`, `p5`, `m2Giles`, `tulilirockz`. Two consumption paths:

| Path | Who uses it | How |
|---|---|---|
| **Reusable workflow** | bluefin, aurora | Calls `reusable-build.yml@v1` + satisfies Justfile contract |
| **À la carte** | bluefin-lts, dakota | Calls individual composite actions |

## The agentic loop

```
Agent reads AGENTS.md → docs/SKILL.md → relevant skill in docs/skills/
  ↓
Opens PR with code change AND skill update in the same commit
  ↓
CODEOWNERS routes review to all four maintainers (bootc-build/, .github/, docs/)
  ↓
Human reviews and merges
  ↓
Human moves @v1 tag → consumers pick up the change
```

Agents **may not** push directly to `main` (branch protection). The `@v1` tag move is **human-only**.

## Your four gates

### 1. PR review
Before approving, check:
- Does the PR include a `docs/skills/` update alongside the code change?
- Is every third-party `uses:` pinned to a full commit SHA with a version comment? Floating tags (`@main`, `@v3`) are a rejection reason — cite `docs/skills/determinism.md`.
- Is the change additive? Removing or renaming an input, or changing a default, requires a version bump and blast-radius note in the PR description.

### 2. Consumer validation (required before merging)
Any action change must pass CI in at least one consuming repo before you merge here. Follow [`docs/skills/consumer-validation.md`](skills/consumer-validation.md):
1. Open a draft PR in `projectbluefin/bluefin` pinned to the feature branch SHA.
2. Wait for CI to pass completely.
3. Link the consumer PR in the actions PR before merging.

### 3. Moving `@v1` (human-only)
After verifying CI is green in the consumer:
```bash
git tag -f v1
git push --force origin v1
```
This affects every consumer repo simultaneously. Do not delegate this to an agent.

### 4. Production gate in consumer repos
Promotion workflows in bluefin, bluefin-lts, and dakota require **2 distinct human approvers** via the `production` GitHub Environment. Repo admins can bypass — every bypass is permanently logged in the Environment deployment history and via `gh api repos/<org>/<repo>/deployments`.

## The self-improving loop

**Knowledge routing rule:** All learnings go to `docs/skills/`. Never to `.github/copilot-instructions.md` (pointer-only, do not edit), and never to a personal agent config. A fix found here belongs to every future agent in this repo.

## When an agent goes off-script

| Symptom | Response |
|---|---|
| Floating tag (`@main`, `@v3`) introduced | Request changes; cite `docs/skills/determinism.md` |
| Agent pushes directly to `main` | Branch protection blocks it; no action needed |
| PR comment spam / duplicate status | Enforce one-comment-per-PR-event policy (from `AGENTS.md`) |
| Agent asks to move `@v1` | Decline — that action is human-only |
| Agent files PR to `cncf/*` or `homebrew/*` | Close it; these namespaces are off-limits per `AGENTS.md` |

## Reference index

| File | Covers |
|---|---|
| [`AGENTS.md`](../AGENTS.md) | All hard rules, gates, namespace map, MCP servers |
| [`docs/SKILL.md`](SKILL.md) | Task-to-skill routing table |
| [`docs/skills/composite-actions.md`](skills/composite-actions.md) | Action authoring and rollout protocol |
| [`docs/skills/consumer-guide.md`](skills/consumer-guide.md) | Onboarding a new image repo |
| [`docs/skills/consumer-validation.md`](skills/consumer-validation.md) | Required consumer validation flow and blast radius |
| [`docs/skills/determinism.md`](skills/determinism.md) | SHA pinning, non-deterministic surfaces |
| [`docs/skills/factory-operations.md`](skills/factory-operations.md) | Production gate, factory health monitor |
| [`.github/CODEOWNERS`](../.github/CODEOWNERS) | Per-path review routing |
| [`.github/workflows/`](../.github/workflows/) | `actionlint`, CI checks |
