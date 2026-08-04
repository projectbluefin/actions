# CI-Gated Renovate Review Exception Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically merge eligible MergeRaptor Renovate updates after all PR checks pass without weakening human PR review requirements.

**Architecture:** `main` keeps its CODEOWNERS and one-approval protection, with the MergeRaptor GitHub App as its only review-bypass actor. A local `workflow_run` caller passes that app's installation credentials to the reusable auto-merge workflow, which verifies Renovate eligibility and the complete PR check rollup before directly squash-merging.

**Tech Stack:** GitHub branch-protection REST API, GitHub Actions reusable workflows, GitHub CLI, GitHub App installation tokens, actionlint.

## Global Constraints

- Preserve the one required approval and CODEOWNERS review requirement for every non-qualifying PR.
- Add only GitHub App ID `3069633` (`mergeraptor`) to the review-bypass allowance; do not add users or teams.
- Merge only `app/mergeraptor` or `renovate[bot]` PRs for which Renovate has enabled auto-merge.
- Merge only after every PR check has completed with `SUCCESS`; do not treat skipped, pending, cancelled, failed, or absent checks as passing.
- Use `MERGERAPTOR_APP_ID` and `MERGERAPTOR_PRIVATE_KEY`; do not add a PAT or a new secret.
- Surface failed `gh pr merge` commands as failures; do not replace them with warnings.

---

## File Structure

| File | Responsibility |
|---|---|
| `.github/workflows/renovate-automerge.yml` | Local `workflow_run` caller that supplies the correct base branch and MergeRaptor app credentials. |
| `.github/workflows/reusable-renovate-automerge.yml` | Reusable qualification, full-check-rollup validation, and direct app-token merge logic. |
| `docs/skills/factory-operations.md` | Durable operational rule for the app-only bypass and CI-gated direct-merge behavior. |

### Task 1: Add the app-only branch-protection bypass

**Files:**
- Modify: GitHub `main` branch protection for `projectbluefin/actions`
- Test: GitHub `main` branch protection response

**Interfaces:**
- Consumes: GitHub App ID `3069633`, current `GET /repos/projectbluefin/actions/branches/main/protection` response.
- Produces: `required_pull_request_reviews.bypass_pull_request_allowances.apps` containing exactly the MergeRaptor app.

- [ ] **Step 1: Read and save the live branch-protection document**

```bash
gh api repos/projectbluefin/actions/branches/main/protection > /tmp/actions-main-protection.json
jq '.required_pull_request_reviews' /tmp/actions-main-protection.json
```

Expected: one required approval, `require_code_owner_reviews: true`, and no existing bypass apps.

- [ ] **Step 2: Build a replacement document that preserves every existing setting**

```bash
jq '
  {
    required_status_checks,
    enforce_admins: .enforce_admins.enabled,
    required_pull_request_reviews: {
      dismiss_stale_reviews: .required_pull_request_reviews.dismiss_stale_reviews,
      require_code_owner_reviews: .required_pull_request_reviews.require_code_owner_reviews,
      require_last_push_approval: .required_pull_request_reviews.require_last_push_approval,
      required_approving_review_count: .required_pull_request_reviews.required_approving_review_count,
      bypass_pull_request_allowances: {
        users: [],
        teams: [],
        apps: [3069633]
      }
    },
    restrictions,
    required_linear_history: .required_linear_history.enabled,
    allow_force_pushes: .allow_force_pushes.enabled,
    allow_deletions: .allow_deletions.enabled,
    block_creations: .block_creations.enabled,
    required_conversation_resolution: .required_conversation_resolution.enabled,
    lock_branch: .lock_branch.enabled,
    allow_fork_syncing: .allow_fork_syncing.enabled
  }
' /tmp/actions-main-protection.json > /tmp/actions-main-protection-with-mergeraptor.json
```

Do not change `required_status_checks`, `enforce_admins`, `restrictions`, or any other protection field from the fetched document.

- [ ] **Step 3: Apply the branch-protection update**

```bash
gh api --method PUT \
  repos/projectbluefin/actions/branches/main/protection \
  --input /tmp/actions-main-protection-with-mergeraptor.json
```

- [ ] **Step 4: Verify the live exception is narrow**

```bash
gh api repos/projectbluefin/actions/branches/main/protection \
  --jq '.required_pull_request_reviews | {
    required_approving_review_count,
    require_code_owner_reviews,
    bypass_pull_request_allowances
  }'
```

Expected: one approval and CODEOWNERS remain enabled; the app list contains only `mergeraptor`, while user and team lists are empty.

### Task 2: Add the repository-specific CI completion caller

**Files:**
- Create: `.github/workflows/renovate-automerge.yml`
- Test: `.github/workflows/renovate-automerge.yml` via `actionlint`

**Interfaces:**
- Consumes: `workflow_run.head_sha`, `MERGERAPTOR_APP_ID`, `MERGERAPTOR_PRIVATE_KEY`.
- Produces: a reusable workflow invocation with `head_sha` and `base_branch: main`.

- [ ] **Step 1: Create the caller workflow**

```yaml
name: Renovate Auto-merge

on:
  workflow_run:
    workflows:
      - Consumer Validation
      - Dependency Review
      - PAT ban — no new unapproved secrets
      - actionlint
      - Unit Tests
    types: [completed]

permissions:
  contents: write
  pull-requests: write

jobs:
  automerge:
    if: github.event.workflow_run.conclusion == 'success'
    uses: ./.github/workflows/reusable-renovate-automerge.yml
    with:
      head_sha: ${{ github.event.workflow_run.head_sha }}
      base_branch: main
    secrets:
      app_id: ${{ secrets.MERGERAPTOR_APP_ID }}
      private_key: ${{ secrets.MERGERAPTOR_PRIVATE_KEY }}
```

Each listed CI workflow can trigger the caller. The reusable workflow performs the final all-check validation, so an early completion cannot merge a PR before sibling checks finish.

- [ ] **Step 2: Run the workflow syntax check**

```bash
actionlint .github/workflows/renovate-automerge.yml
```

Expected: exit status 0.

- [ ] **Step 3: Commit the caller**

```bash
git add .github/workflows/renovate-automerge.yml
git commit -m "ci(actions): trigger CI-gated Renovate automerge" \
  -m "Assisted-by: GPT-5.6 Terra via GitHub Copilot" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Enforce qualification and complete-check validation before merging

**Files:**
- Modify: `.github/workflows/reusable-renovate-automerge.yml`
- Test: `.github/workflows/reusable-renovate-automerge.yml` via `actionlint`

**Interfaces:**
- Consumes: `head_sha`, `base_branch`, optional `app_id` and `private_key` workflow-call secrets.
- Produces: a direct squash merge only for an eligible, all-green Renovate PR; a nonzero exit when an attempted merge is denied.

- [ ] **Step 1: Preserve app-token minting and make it the caller contract**

Keep the `app_id` and `private_key` workflow-call secrets plus the
`actions/create-github-app-token` step. Set `GH_TOKEN` in every `gh` step to:

```yaml
${{ steps.app-token.outputs.token || secrets.token || github.token }}
```

The app identity, not `github-actions[bot]`, must execute the direct merge.

- [ ] **Step 2: Query the matching PR and require Renovate auto-merge eligibility**

Replace the author-only selection with a GraphQL query that returns the PR
number, author login, and `autoMergeRequest`. Write an empty `pr_number` when
there is no open PR for `HEAD_SHA`, the author is not `app/mergeraptor` or
`renovate[bot]`, or `autoMergeRequest` is null.

```bash
PR_NUMBER=$(gh api graphql -f query='
  query($owner: String!, $repo: String!, $head: String!, $base: String!) {
    repository(owner: $owner, name: $repo) {
      pullRequests(first: 100, states: OPEN, baseRefName: $base) {
        nodes {
          number
          headRefOid
          author { login }
          autoMergeRequest { enabledAt }
        }
      }
    }
  }' \
  -f owner="${GITHUB_REPOSITORY_OWNER}" \
  -f repo="${GITHUB_REPOSITORY#*/}" \
  -f head="$HEAD_SHA" \
  -f base="$BASE_BRANCH" \
  | jq -r --arg head "$HEAD_SHA" '.data.repository.pullRequests.nodes[]
    | select(.headRefOid == $head)
    | select(.author.login == "app/mergeraptor" or .author.login == "renovate[bot]")
    | select(.autoMergeRequest != null)
    | .number' | head -1)
```

- [ ] **Step 3: Reject any incomplete or non-successful check rollup**

Before `gh pr merge`, inspect every check state:

```bash
CHECKS=$(gh pr checks "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json name,state)
if [ "$(jq 'length' <<<"$CHECKS")" -eq 0 ] ||
   [ "$(jq '[.[] | select(.state != "SUCCESS")] | length' <<<"$CHECKS")" -ne 0 ]; then
  echo "PR #$PR_NUMBER does not have a complete successful check rollup; skipping"
  exit 0
fi
```

This returns successfully only because a later successful `workflow_run`
event will retry it. It must not run `gh pr merge` in this state.

- [ ] **Step 4: Make the direct merge failure visible**

Use the existing direct squash merge without `--auto`, but remove the warning
fallback and success message after a failing command:

```bash
gh pr merge "$PR_NUMBER" --squash --repo "$GITHUB_REPOSITORY"
echo "Merged PR #$PR_NUMBER"
```

- [ ] **Step 5: Run the workflow syntax check**

```bash
actionlint .github/workflows/reusable-renovate-automerge.yml
```

Expected: exit status 0.

- [ ] **Step 6: Commit the reusable workflow hardening**

```bash
git add .github/workflows/reusable-renovate-automerge.yml
git commit -m "fix(ci): gate Renovate bypass merges on all checks" \
  -m "Assisted-by: GPT-5.6 Terra via GitHub Copilot" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Document and verify the live behavior

**Files:**
- Modify: `docs/skills/factory-operations.md`
- Test: `actionlint .github/workflows/renovate-automerge.yml .github/workflows/reusable-renovate-automerge.yml`

**Interfaces:**
- Consumes: implemented caller and reusable workflow.
- Produces: an evergreen operator procedure for the app-only bypass.

- [ ] **Step 1: Update the Renovate section with the exemption rule**

State that `main` retains required reviews, MergeRaptor is the sole
branch-protection bypass app, and only the CI-gated reusable workflow may use
its installation token to merge Renovate-eligible PRs. Include the
operational check:

```bash
gh api repos/projectbluefin/actions/branches/main/protection \
  --jq '.required_pull_request_reviews.bypass_pull_request_allowances'
```

- [ ] **Step 2: Validate both changed workflows**

```bash
actionlint \
  .github/workflows/renovate-automerge.yml \
  .github/workflows/reusable-renovate-automerge.yml
```

Expected: exit status 0.

- [ ] **Step 3: Open a draft consumer-validation PR and run CI**

Open a draft PR in `projectbluefin/bluefin` targeting `testing`, using
`projectbluefin/actions@v1` as normal. Record the draft PR and successful run
URLs in the actions PR description, as required by
`docs/skills/consumer-validation.md`.

- [ ] **Step 4: Exercise the exception with a qualifying Renovate PR**

After the actions PR is merged and `v1` advances, confirm an existing or new
digest, pin, patch, or minor MergeRaptor PR merges after every PR check
succeeds without a human review. Confirm that a major Renovate update and a
human-authored PR remain blocked by the review rule.

- [ ] **Step 5: Commit the documentation**

```bash
git add docs/skills/factory-operations.md
git commit -m "docs(ci): document Renovate review bypass" \
  -m "Assisted-by: GPT-5.6 Terra via GitHub Copilot" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Plan Self-Review

- **Spec coverage:** Task 1 implements the app-only bypass while preserving
  human review requirements. Tasks 2 and 3 implement the local caller,
  Renovate eligibility restriction, complete-check gate, and visible merge
  failures. Task 4 documents and exercises both allowed and disallowed paths.
- **Placeholder scan:** No placeholders or deferred implementation decisions
  remain.
- **Consistency:** The same MergeRaptor App ID, secrets, base branch, author
  identities, and all-success requirement are used throughout.
