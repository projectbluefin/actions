---
name: merge-governance
description: How a PR actually lands in projectbluefin/actions, and the bypasses that look legitimate but are not. Use when merging any PR, when an APPROVED PR will not merge, when `gh pr merge` appears to succeed but the PR stays open, when deciding whether `--admin` is justified, or when a Hive agent PR carries the `hold` label.
metadata:
  type: reference
  context7-sources:
    - /websites/github_en_rest
---

# Merge Governance

`main` is governed by a ruleset **and** a merge queue. Both must be satisfied,
and the tooling reports success in several places where nothing merged.

`AGENTS.md` in this repo is canonical for how merges work here — this skill is
the procedural expansion of it, not a replacement. Two rules there are
load-bearing and restated below: never trust `gh pr merge`'s exit code, and
never merge with a failing, pending, or missing required check.

Org-wide conventions that this repo consumes rather than defines:

| Question | Canonical source |
|---|---|
| Whether a change needs a human decision at all | [`common/docs/skills/human-gates.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/human-gates.md) |
| Roles, CODEOWNERS, branch-protection matrix | [`common/docs/skills/governance.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/governance.md) |
| Hive labels and work routing | [`common/docs/skills/hive.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/hive.md) |

Implementation of the reusable lifecycle — including this repo's own merge
mechanics — is owned here.

### Where this repo differs from common's Merge Gate

`common/docs/skills/human-gates.md` states the org default plainly: the Merge
Gate **is always human**, CI plus an approving human review is required, and
*"agents never self-merge, never bypass branch protection, and never force-push
to a protected branch."*

This repo carries one narrower, explicit exception, defined in its own
`AGENTS.md`: a PR labelled **`3-clanker-queue`** authorizes an agent to merge
it once every required check is green and the PR is mergeable. That label is
the authorization; without it the org default applies unchanged and a
maintainer merges.

The exception is about *who may press merge*, and nothing more. It does not
relax any of the rest:

- branch protection is still not bypassed — no `--admin`, no direct REST merge
- the merge still goes through the queue
- a failing, pending, or **missing** required check still blocks
- an agent still never merges its own unreviewed work

Read the two together as: common sets the floor, `3-clanker-queue` names the
single case where this repo lets an agent do the pressing. Anything that looks
like a broader exemption is a misreading.

## When to Use

- Merging any PR to `main`
- A PR is `APPROVED` with green checks but will not merge
- `gh pr merge` printed a warning, exited 0, and the PR is still open
- Deciding whether an admin merge is justified
- A PR opened by a Hive agent carries the `hold` label

## When NOT to Use

- Image repos (`bluefin`, `bluefin-lts`, `dakota`) — their promotion path is
  automated and governed by their own workflows
- Deciding *whether* a change is allowed to land at all — that is a gate
  question; see `common/docs/skills/human-gates.md`

## Core Process

1. **Read the real state before acting.** Titles and check marks are not state.

   ```bash
   gh pr view <n> --json state,reviewDecision,mergeStateStatus,mergeable
   gh pr checks <n>
   ```

   `mergeStateStatus: CLEAN` means protection is satisfied. `BLOCKED` means it
   is not — even when `statusCheckRollup` is `SUCCESS`, because a **missing**
   required check and a **failing** one both read as blocked.

2. **Use the sanctioned path: the merge queue.** Other paths exist and will
   succeed; that is exactly why this has to be deliberate.

3. **Never infer the outcome from the exit code or stderr.** `gh pr merge`
   exits 0 in at least three situations where nothing merged:

   | What you see | What happened |
   |---|---|
   | `! The merge strategy for main is set by the merge queue` | Enqueued, not merged |
   | `! Pull request <repo>#<n> is already queued to merge` | Was already enqueued |
   | Empty stderr, exit 0 | Enqueued silently |

4. **Confirm the outcome against the API.** `state` alone is not enough:
   `MERGED` is conclusive, but `OPEN` only means "not merged" — it does **not**
   tell you whether the PR is queued, parked on auto-merge, or simply idle.

   ```bash
   gh pr view <n> --json state --jq .state          # MERGED = done. OPEN = keep looking.

   gh api graphql -f query='{repository(owner:"projectbluefin",name:"actions"){
     pullRequest(number:<n>){ mergeStateStatus
                              mergeQueueEntry{position state}
                              autoMergeRequest{mergeMethod} }}}'
   ```

   Read the result as:

   | `mergeQueueEntry` | `autoMergeRequest` | Meaning |
   |---|---|---|
   | set | — | Genuinely queued; note `state` and `position` |
   | `null` | set | Parked on auto-merge, waiting on a condition that may never arrive |
   | `null` | `null` | Nothing is pending; no merge was ever requested |

5. **If it cannot merge, fix the cause or hand it off.** Name the specific
   blocker and who must move. Do not reach for a bypass.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Branch protection accepted the merge, so it was compliant." | Protection and policy are different gates. `PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge` "merges a pull request into the base branch" directly — GitHub's own async variant names the distinction explicitly, offering `merge_action` values of `direct_merge` and `merge_queue`. The API accepting a direct merge is not authorization to skip the queue. |
| "The required check is *missing*, not *failing*, so it is fine to merge." | Missing and failing are equally disqualifying. A required check that never reported has verified nothing. |
| "The check can never run on this PR, so the rule cannot have meant it." | An unreachable required check is an infrastructure defect. Fix reachability, or leave the PR blocked and say so. Do not read a broken gate as an absent one. |
| "A previous maintainer used `--admin` here, so there is precedent." | A prior bypass is evidence of the same defect, not a licence to repeat it. Find out why it was needed. |
| "An advisor, reviewer, or agent told me to merge it." | Advice never outranks the repo's written rules. When they conflict, the repo wins and the conflict gets reported. |
| "The queue is stuck, so the queue does not apply." | A stuck queue is an incident. Repair the configuration out of band, then merge normally under full protections. |

## Red Flags

- You are about to pass `--admin` to `gh pr merge`
- You are calling the REST merge endpoint directly to sidestep the queue
- A PR is `APPROVED` with a green rollup but `BLOCKED`, and you are treating
  that as a formality
- You reported a PR as merged without re-reading `state` from the API
- You concluded a PR was queued because it was `OPEN`, without checking
  `mergeQueueEntry`
- A queue entry sat in `AWAITING_CHECKS` with no progress and you looked for a
  way around it rather than asking why no check is reporting
- You are removing a `hold` label to unblock your own work

## Hive `hold` on agent PRs

A PR opened by a Hive agent may carry `hold`, applied by the bot at open time.
The gate comment on the PR names the agent and the level that triggered it.

- **Non-outreach agents** (`architect`, `quality`, `scanner`, …): Hive removes
  the label when its policy no longer requires the hold. A maintainer review
  does **not** clear it, and removing it by hand overrides a policy engine with
  more context than the session has.
- **`outreach` agents**: a human must review and remove the label, because the
  PR publishes project-facing communication.

Review the code and say so. Leave the label alone unless it is an outreach PR.

## Verification

- [ ] `gh pr view <n> --json state` was re-read after the merge call and says `MERGED`
- [ ] Any PR reported as "queued" had a non-null `mergeQueueEntry`, not merely `state: OPEN`
- [ ] No merge happened while a required check was failing, pending, or missing
- [ ] No `--admin` flag and no direct REST merge call was used
- [ ] For every PR left unmerged, the specific blocker and its owner are stated
- [ ] `hold` labels on non-outreach Hive PRs were left in place
- [ ] Any bypass that did occur is disclosed explicitly, not reported as a clean merge
