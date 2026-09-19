---
name: factory-operations
description: Use when configuring production approval or automated verification gates, promotion cadence, merge queues, factory health monitoring, or Renovate auto-merge.
metadata:
  type: reference
  context7-sources:
    - /renovatebot/renovate
---

# Factory Operations Skill

Covers systems that keep the projectbluefin factory safe:

1. **Production gate** - repository-specific human approval or automated verification before a build reaches `:stable`
2. **Promotion cadence** - per-repo schedule, explicit enrollment, merge-queue selection, and E2E policy
3. **Factory health monitor** - scheduled pipeline health monitoring with automatic issue creation
4. **Renovate auto-merge** - automated dependency bump management

---

## 1. Production Gate (Track C-1)

### What it is

Production authorization is repository-specific. Repositories using a GitHub
Environment can require distinct human approvers. Bluefin instead uses an
automated chain: exact-source-SHA E2E success, cosign verification, Tuesday UTC
release-window approval, and merge-queue enrollment after the gate succeeds.

### Where it lives

| Repo | Workflow | Gate |
|---|---|---|
| `projectbluefin/bluefin` | `promote-testing-to-main.yml` | E2E + cosign + Tuesday window |
| `projectbluefin/dakota` | `weekly-testing-promotion.yml` | `production` environment |
| `projectbluefin/bluefin-lts` | `scheduled-lts-release.yml` | `production` environment |

### Workflow snippet

```yaml
jobs:
  promote:
    runs-on: ubuntu-latest
    environment:
      name: production
      url: https://ghcr.io/projectbluefin/dakota:stable
    steps:
      - # ... SHA-lock + verify-e2e + skopeo copy ...
```

### Manual GitHub UI setup (environment-gated repos only)

For Dakota and Bluefin LTS, after the workflow change is merged:

1. Go to the repo → **Settings → Environments → New environment**
2. Name: `production`
3. Set **Required reviewers** - list the maintainers.
4. Set the **required count to 2** (two distinct approvals).
5. Restrict to the release branch.

### Verification for environment-gated repos

- Trigger the promotion workflow via `workflow_dispatch`.
- Confirm the job pauses with a yellow "Waiting for approval" status.
- One reviewer approves → job stays paused.
- Second reviewer approves → job runs.
- Author approving their own dispatch is blocked when approval is required.

### What it does NOT prevent

Repo admins can bypass Environment rules. All bypasses are permanently visible in:
- `gh api repos/<org>/<repo>/deployments` - every deployment record
- The Environment's deployment history page in GitHub UI

The protection is friction-ful for accidental/casual bypasses, not cryptographically airtight. This is the appropriate bar for a trusted team of 4.

---

## 2. Promotion Cadence and Merge Queue Contract

Each consumer repo promotes `:testing` → `:stable` (or `:lts`) via a thin caller to
`reusable-promote-squash.yml@v1`. The caller owns cadence through
`enqueue_promotion`; `use_merge_queue` selects the target branch's merge mechanism
and must not be overloaded as an on/off switch.

### Per-repo schedule and inputs

| Repo | Cron (UTC) | `enqueue_promotion` | `use_merge_queue` | `run_e2e` | Notes |
|---|---|---|---|---|---|
| `projectbluefin/bluefin` | daily `0 4 * * *` | Tuesday schedule or manual dispatch | `true` | `true` | push and non-Tuesday runs refresh the PR without enqueueing |
| `projectbluefin/bluefin-lts` | Tuesday `0 4 * * 2` | default `true` | `false` | `false` | direct branch builds; no squash promotion PR |
| `projectbluefin/dakota` | Tuesday `0 4 * * 2` | schedule or manual dispatch | repository policy | repository policy | weekly release path only |

### Release-window enrollment

Callers that refresh a promotion PR outside the release window must pass an
explicit boolean:

```yaml
enqueue_promotion: ${{ needs.release_window.outputs.should_enqueue == 'true' }}
use_merge_queue: true
```

The reusable workflow first builds the squash PR and runs the release gate. Its
`enqueue` job depends on both jobs and requires `needs.gate.result == 'success'`.
Cosign or E2E failure therefore cannot race with queue enrollment. Do not move
enrollment back into the PR-construction job.

`enablePullRequestAutoMerge` is blocked when the target branch has a merge queue
ruleset. `use_merge_queue: true` selects `enqueuePullRequest`; it does not decide
whether a release window is open.

### E2E policy

Set `run_e2e: true` when the consumer's post-build E2E workflow is the release
qualification signal. The gate looks up the completed run for the exact source
branch SHA and refuses enrollment unless it succeeded. `e2e_image` must be
non-empty to activate that lookup. Consumers that run an equivalent production
environment gate may leave this false, but must document the alternate trust
boundary.

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

Token generation is best-effort so a GitHub App installation permission mismatch cannot prevent the
health checks from running. If the cross-repo token is unavailable, use the workflow's repository-scoped
`github.token` to file alerts in `projectbluefin/actions`. This preserves monitoring and alerting while
keeping the fallback credential unable to write outside its source repository.

**`MERGERAPTOR_APP_ID` is a `secrets.*` value, not a `vars.*` value** — see the approved-secrets
table in `docs/skills/supply-chain.md`. Passing `vars.MERGERAPTOR_APP_ID` to
`actions/create-github-app-token` silently resolves to an empty string (repo/org variables and
secrets are separate namespaces) and the step fails with
`The 'client-id' (or deprecated 'app-id') input must be set to a non-empty string.` Always wire it
as `client-id: ${{ secrets.MERGERAPTOR_APP_ID }}` — use `client-id`, not the deprecated `app-id`
input, for consistency across workflows.

### Output

The workflow always prints a markdown summary table to stdout and `$GITHUB_STEP_SUMMARY`, even when no
issues are opened.

---

## 4. Renovate - Automated Dependency Maintenance

### What it does

Renovate runs as the MergeRaptors GitHub App and opens PRs to bump pinned action SHAs and digests. Qualifying PRs auto-merge when CI passes — no human review needed, even though `main` requires one approval and CODEOWNERS review. See "CI-gated review bypass" below for how that is safe.

### Config

Two files co-exist:
- `.github/renovate.json5` - base org config (inherited from `projectbluefin/renovate-config`)
- `renovate.json` - repo-level overrides, including the `packageRules` automerge block

Renovate's `automerge: true` does not merge the PR itself here; it sets GitHub's
`autoMergeRequest` on the PR, which the auto-merge workflow reads as the
eligibility signal. `renovate.json` is therefore the single source of truth for
*what* may merge unattended — change policy there, not in the workflow.

**What auto-merges:** whatever `renovate.json` marks auto-mergeable (SHA digest bumps and pin updates), once every check on the PR has completed successfully. These carry no behavior change.

**What never auto-merges:** major version bumps, anything Renovate did not mark auto-mergeable, drafts, conflicting PRs, and any PR with a failing, pending, cancelled, or empty check rollup. Those still require a human approval and merge, or the `clanker-queue` label authorizing an agent to merge after confirming every required check is green.

### CI-gated review bypass

`main` keeps `required_approving_review_count: 1` and `require_code_owner_reviews: true` for everyone. The MergeRaptor GitHub App is the **only** entry in the branch-protection review-bypass allowance — no users, no teams:

```bash
gh api repos/projectbluefin/actions/branches/main/protection \
  --jq '.required_pull_request_reviews.bypass_pull_request_allowances'
```

Expected: `apps` contains only `mergeraptor`; `users` and `teams` are empty.

The bypass is only reachable through automation:

| Piece | Responsibility |
|---|---|
| `.github/workflows/renovate-automerge.yml` | Local `workflow_run` caller. Fires on every CI workflow completion, passes `base_branch: main`, `require_auto_merge: true`, and the MergeRaptor app credentials. |
| `.github/workflows/reusable-renovate-automerge.yml` | Mints the app installation token, qualifies the PR, validates the full check rollup, and merges (respecting a merge queue if one exists). |

Three gates must all pass before a merge happens:

1. **Author** is `mergeraptor` or `renovate` (in any spelling — see the gotcha below).
2. **Renovate enabled auto-merge** on the PR (`autoMergeRequest != null`), i.e. `renovate.json` says it qualifies.
3. **Every check is green *and* nothing is still running.** Nonterminal check states — `PENDING`, `QUEUED`, `IN_PROGRESS`, `WAITING`, `REQUESTED`, `EXPECTED` (the same set `gh pr checks` places in its own `pending` bucket) — are awaited up to `check_timeout_seconds`, never treated as failures. `SKIPPED` and `NEUTRAL` are non-blocking, matching GitHub's own merge semantics. Only terminal failure conclusions (`FAILURE`, `CANCELLED`, `TIMED_OUT`, `ACTION_REQUIRED`, `STARTUP_FAILURE`, `STALE`, `ERROR`) or an unrecognized state block outright.

**Gotcha — an absent check is not a passing check.** `gh pr checks` reports only the check-runs that currently *exist*. A workflow that is queued but has not yet registered a check-run is simply **missing from the rollup**, not `PENDING`; and re-running a workflow removes its check-runs entirely while they re-queue. A naive "nothing is pending, so we're done" gate will happily merge with most checks never having run. Since this workflow is triggered by *one* CI workflow completing while siblings may still be queued, that race is the normal case, not an edge case. Cross-check in-flight runs for the same commit:

```bash
gh run list --repo "$GITHUB_REPOSITORY" --commit "$HEAD_SHA" --limit 100 \
  --json status --jq '[.[] | select(.status != "completed")] | length'
```

Treat a non-zero count, an empty rollup, *and* an unreadable run list as "keep waiting" — all three must fail closed. Only an all-`SUCCESS` rollup with zero in-flight runs may merge.

Gate 3 is why it is safe for any CI workflow to trigger the caller: an
early-finishing workflow cannot merge ahead of its still-running siblings. A
skip is **not** a failure — the next successful `workflow_run` event retries the
whole evaluation.

**Gotcha — bot author login differs between REST and GraphQL.** For a GitHub App, GraphQL's `author.login` returns the bare slug `mergeraptor`, while REST and `gh pr list` return `app/mergeraptor`, and a legacy bot user returns `renovate[bot]`. Any author matcher must normalise all three spellings or it will silently match nothing. Verify a matcher against live data before trusting it:

```bash
gh api graphql -f query='{repository(owner:"projectbluefin",name:"actions"){
  pullRequests(first:20,states:OPEN,baseRefName:"main"){
    nodes{number author{login} autoMergeRequest{enabledAt}}}}}'
```

**Gotcha — `gh pr merge --auto` cannot be used here.** GitHub's auto-merge queue does not honour `bypass_pull_request_allowances`; only a direct merge does. `--auto` also errors with "Protected branch rules not configured" on unprotected base branches. The workflow therefore always does a direct merge, with the check-rollup gate standing in for what `--auto` would have waited on.

**Gotcha — a merge queue rejects any explicit merge strategy, but only as a *warning*.** When the base branch has a merge queue, `gh pr merge --squash` prints `! The merge strategy for main is set by the merge queue` **and still exits 0**, having enqueued the PR. Never infer merge-queue behaviour from the exit status — match the stderr text. Two strings matter, and they do not share a substring:

| Message (stderr, `!`-prefixed) | Meaning |
|---|---|
| `The merge strategy for <branch> is set by the merge queue` | strategy flag ignored; PR was enqueued |
| `Pull request <repo>#<n> is already queued to merge` | a previous attempt enqueued it — success, not failure |

The reusable workflow exposes `merge_method` (`squash` by default, `queue` to omit the flag entirely), treats both messages as success, and retries without the flag if a future `gh` version hard-fails instead of warning.

**Never infer the merge outcome from stderr text or the exit code.** A plain `gh pr merge` with no strategy flag enqueues the PR while printing *nothing at all* and exiting 0 — indistinguishable from a real merge by output alone. Conversely, gh's success line goes to stderr and includes the PR title, so a PR titled "…update merge-queue action" would trip a naive `grep "merge queue"`. Ask GitHub for the actual state instead:

```bash
gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json state --jq .state
# MERGED = landed; OPEN = enqueued, the queue lands it ~60s later
```

**Gotcha — the `secrets` context is unavailable in step-level `if:`.** To conditionally mint an app token in a reusable workflow, mirror credential presence into job-level `env` first (`HAS_APP_CREDS: ${{ secrets.app_id != '' && secrets.private_key != '' }}`) and branch on `env.HAS_APP_CREDS`.

**Consumer-validation exemption:** Renovate PRs (author login ending in `[bot]` or starting with `app/`) are automatically exempt from the consumer PR + CI run evidence requirement, even when they touch action files. See `docs/skills/consumer-validation.md`.

### Validation workflow

`.github/workflows/validate-renovate.yml` runs `renovate-config-validator --strict` on PRs and pushes that touch either Renovate config file. Changes that fail validation are caught before merging.

### Auto-merge repo setting

The repository has `allow_auto_merge: true` enabled. Without this, GitHub ignores the `automerge` setting regardless of config.

### Automated wiring assertion

`.github/workflows/renovate-automerge-wiring.yml` runs `scripts/renovate-automerge-wiring-check.sh` on a daily schedule (and via `workflow_dispatch`). It asserts the declarative facts that make a real mergeraptor PR mergeable — `allow_auto_merge` is true, and the MergeRaptor app is the **sole** review-bypass actor on `main` — and reports any live mergeraptor/renovate PR with auto-merge enabled. The end-to-end merge itself needs a real mergeraptor PR (created out-of-band by Renovate) and cannot be forced from CI, so this check is the part of issue #403 that is automatable: it fails loudly if the wiring drifts, and its passing is the precondition evidence that the merge step in `renovate-automerge.yml` can land a qualifying PR. Covered by `tests/bats/test_renovate_automerge_wiring_check.bats`.

### Relationship to `@v1`

Renovate keeps SHA pins current **for third-party actions in this repo**. Consumers don’t see the updates until a maintainer advances the `@v1` tag. See the `@v1` runbook in AGENTS.md for the exact commands.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Renovate PR won't auto-merge | `allow_auto_merge` disabled on repo | `gh api -X PATCH repos/projectbluefin/actions -f allow_auto_merge=true` |
| Renovate PR sits green and unmerged | `autoMergeRequest` is null — `renovate.json` doesn't mark this update type auto-mergeable (e.g. a major bump) | Expected. Review and merge by hand, or widen the `packageRules` automerge match |
| Auto-merge job logs "No qualifying Renovate/Mergeraptor PR" on a real Renovate PR | Author matcher missed a login spelling, or the PR is a draft/conflicting | Compare against the live GraphQL `author.login` — GraphQL says `mergeraptor`, REST says `app/mergeraptor` |
| Auto-merge job reaches the merge step and `gh pr merge` fails on review requirements | MergeRaptor missing from `bypass_pull_request_allowances`, or the job used `github.token` instead of the app token | Check the bypass list; confirm the caller passes `app_id` + `private_key` |
| Renovate PR consumer-validation fails | Bot exemption not firing | Verify author login ends in `[bot]` or starts with `app/` - check `gh pr view NNN --json author` |
| Renovate PR has merge conflict | Another bump landed first; branches diverged | Locally checkout the branch, `git rebase origin/main`, force-push |
| Two Renovate PRs update the same action | Both opened before either merged | Close the older/lower version one; merge the newer |
| Dependency Dashboard (issue #42) shows PRs as "Open" | Renovate dashboard is eventually consistent - PRs may already be merged | Confirm with `gh pr view NNN --json mergedAt` before acting; the dashboard self-corrects on next Renovate run |
| Renovate warns: "Fallback to renovate.json as preset is deprecated" | Config file named `renovate.json` instead of `default.json` | Rename: `git mv renovate.json default.json` - content stays identical |

### Verification — is auto-merge actually wired up?

The bypass allowance and the workflow are independent halves. Configuring only one
leaves the system inert but looking correct. Check all five:

- [ ] `.github/workflows/renovate-automerge.yml` exists in **this** repo and its
      `workflow_run.workflows:` list names every CI workflow that gates `main`.
- [ ] The branch-protection bypass lists app `mergeraptor` and nothing else
      (command at the top of this section).
- [ ] `MERGERAPTOR_APP_ID` and `MERGERAPTOR_PRIVATE_KEY` are set as repo secrets —
      without them the job runs as `github-actions[bot]`, which has no bypass and
      cannot merge.
- [ ] `gh api repos/projectbluefin/actions --jq .allow_auto_merge` returns `true`.
- [ ] A recent run of the "Renovate Auto-merge" workflow exists and its log ends in
      either a merge or an explicit skip reason — a workflow that never triggers is
      the failure mode this checklist exists to catch:
      ```bash
      gh run list --repo projectbluefin/actions --workflow renovate-automerge.yml --limit 5
      ```


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

### Queue-entry guard: avoid branch rewrites when PR is merge-queued

When a promotion PR is enrolled in a merge queue, GitHub locks the head branch and rejects
any force-push or branch mutation with `GH006: Ref cannot be updated: A pull request using this branch as its head is in the merge queue and cannot be modified.` Subsequent workflow runs (e.g. daily cron, push to testing, or PR review triggers) must not attempt to rebuild or mutate the branch while it is queued.

Before checkout or branch mutation, query GraphQL for an existing `mergeQueueEntry` on the
open promotion PR. If a queue entry exists, emit an informative notice, set `promoted=false`,
and exit 0 so the merge queue can progress undisturbed:

```bash
# shellcheck disable=SC2016  # GraphQL variables, not shell variables
PR_DATA=$(gh api graphql \
  -f query='query($owner: String!, $repo: String!, $head: String!, $base: String!) {
    repository(owner: $owner, name: $repo) {
      pullRequests(headRefName: $head, baseRefName: $base, states: OPEN, first: 1) {
        nodes {
          id
          number
          url
          mergeQueueEntry {
            id
            state
          }
        }
      }
    }
  }' \
  -F owner="$REPO_OWNER" \
  -F repo="$REPO_NAME" \
  -F head="$PROMOTION_BRANCH" \
  -F base="$TARGET_BRANCH" \
  --jq '.data.repository.pullRequests.nodes[0] // empty' 2>/dev/null) || PR_DATA=""

if [ -n "$PR_DATA" ]; then
  QUEUE_ENTRY_ID=$(echo "$PR_DATA" | jq -r '.mergeQueueEntry.id // empty' 2>/dev/null || echo "")
  if [ -n "$QUEUE_ENTRY_ID" ]; then
    echo "::notice::Promotion PR #${PR_NUMBER} has active merge queue entry (${QUEUE_ENTRY_ID}) — skipping branch mutation"
    echo "promoted=false" >> "$GITHUB_OUTPUT"
    exit 0
  fi
fi
```

### gh api failure output goes to stdout — capture defensively

`gh api` on a failed request (HTTP 404/500) prints the API error body to **stdout**
and the human-readable `gh: ...` message to **stderr**, then exits non-zero. A
capture like this is therefore NOT safe — `2>/dev/null` only drops the stderr
message, and the error JSON becomes the variable value:

```bash
# WRONG — SHA becomes '{"message":"Not Found",...}' on a missing ref, because
# the error body is on stdout and '' only gets appended, never substituted
SHA=$(gh api repos/$REPO/git/ref/heads/$BRANCH --jq '.object.sha' 2>/dev/null || echo "")
```

Use the exit status to replace the value instead of `|| echo ""`:

```bash
# RIGHT — SHA is empty on failure, populated on success
SHA=$(gh api repos/$REPO/git/ref/heads/$BRANCH --jq '.object.sha' 2>/dev/null) || SHA=""
```

Apply this pattern to every variable captured from a `gh api` call that can 404.
A leaked error JSON travels into downstream URLs and produces confusing failures
like `unsupported protocol scheme ""`.

### Branch-derived names must be defined once at the job level

Any value derived from workflow inputs and used by multiple steps (squash branch
name, image ref, tag list) belongs in the **job-level `env:`** block as a single
expression:

```yaml
env:
  PROMOTION_BRANCH: ${{ format('auto/promote-{0}-to-{1}', inputs.source_branch, inputs.target_branch) }}
```

Duplicating the expression in each step's `env:` invites one step to be edited
and the others to drift. This bit the promote-squash workflow: rebuild/upsert
hardcoded the squash branch name while the validate-status step derived it from
the inputs, so any caller with a non-default branch model (main→stable) pushed
one branch and looked up another — 404-ing before auto-merge could run. With the
name defined once, all steps stay in lockstep.

### reusable-sync-branches: optional GH_TOKEN + force-reset for diverged branches

`reusable-sync-branches.yml` merges `source_branch` into `target_branch` after a promotion.
Two patterns to know:

**Protected branches:** The workflow accepts an optional `GH_TOKEN` secret from the caller.
When provided, it uses a GitHub App token to bypass protected-branch push rules. Without it,
`github.token` is used — which fails on protected branches.

**Diverged target:** If the target branch has commits not in source (e.g. Renovate PRs landed on
`testing` while `main` got CI fixes), the workflow's default is to fast-forward merge when the
target is simply behind, or **refuse** when the branches have diverged. It force-resets `target`
to `source` **only** when the caller sets `allow_force_reset: true` AND `target_branch` is not the
repository default branch. Never force-reset a branch that receives human work — the default branch
is never permitted, and a caller that pointed `target_branch` at its `main` got a 100-commit
force-reset attempt (stopped only by branch protection; see issue #543). Consumers whose
`main`→`testing` sync relied on force-reset to recover from Renovate divergence must add
`allow_force_reset: true` to their `with:` block or their syncs fail closed (loudly, no data loss).

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

---

## When to Use

Use this skill when:
- Setting up or auditing the machine-enforced 2-human production approval gate in consumer repositories.
- Modifying promotion schedules, cadence, or merge-queue integration across bluefin, dakota, or bluefin-lts.
- Investigating factory health monitoring alerts or failure issue generation in `projectbluefin/common`.
- Debugging or configuring Renovate dependency updates and automated merge rules for first-party or third-party pins.
- Verifying the end-to-end promotion PR format (Design C) and checklist markers.

## When NOT to Use

Do not use this skill to:
- Modify individual composite action implementations (use `composite-actions.md`).
- Bypass the 2-human approval gate or force promotions directly to stable without verification.
- Manually edit generated promotion PRs while automation is active.

## Core Process

1. **Production gate enforcement**: Configure GitHub Environment `production` with 2 required maintainer reviewers; ensure promotional workflows declare `environment: production`.
2. **Promotion workflow orchestration**: Validate that weekly promotions lock the main HEAD SHA, execute full e2e testsuites, and post structured Design C promotion PRs.
3. **Merge-queue compliance**: Follow the merge-queue contract (`use_merge_queue`), ensuring queue entry guards prevent out-of-order race conditions.
4. **Health monitoring**: Maintain the 6-hour scheduled health check; confirm automated alerts fire when pipeline success rates drop below 80%.
5. **Renovate automation**: Configure Renovate presets and package rules; ensure first-party references are ignored and third-party SHA bumps auto-merge upon passing CI.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Only one maintainer is available, so bypass the environment gate." | The 2-human rule is an intentional safety invariant preventing single-point compromise or accidental releases. |
| "Promotion can skip e2e tests because testing passed yesterday." | Builds drift constantly with upstream packages; promotional gates require explicit e2e verification of the exact SHA. |
| "A single failing run isn't worth investigating." | Repeated silent failures degrade pipeline health until mass breakages occur. |
| "Renovate auto-merge doesn't need verification if actionlint passed." | Auto-merge can fail silently if GitHub App credentials or branch protection rules are misconfigured. |

## Red Flags

- Production promotion jobs executing without an `environment: production` block.
- Self-approval or single-human approvals pushing images to the `:stable` tag.
- Disabling `run_e2e` or promotion gates without explicit maintainer sign-off.
- Renovate creating duplicate PRs to pin first-party `projectbluefin/actions` references.
- Missing `MERGERAPTOR_APP_ID` or private keys leading to silent auto-merge workflow failures.

## Verification

- [ ] GitHub Environment `production` is configured with 2 required maintainer reviewers.
- [ ] Weekly promotion workflows specify `environment: production`.
- [ ] Merge queue configuration matches each repository's promotion contract (`use_merge_queue`).
- [ ] Factory health monitor scheduled runs complete and create alert issues when failure thresholds are crossed.
- [ ] Renovate auto-merge workflow runs with valid GitHub App authentication and branch protection bypasses.
