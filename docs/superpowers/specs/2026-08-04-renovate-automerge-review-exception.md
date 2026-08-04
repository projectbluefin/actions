# CI-Gated Renovate Review Exception

**Date:** 2026-08-04
**Scope:** `main` branch protection and Renovate auto-merge workflow
**Affects:** `projectbluefin/actions`

---

## Problem

`main` requires one CODEOWNERS approval. Renovate enables GitHub auto-merge
for eligible digest, pin, patch, and minor updates, but those pull requests
remain blocked because no human approval exists. All checks can pass while the
dependency queue accumulates.

Removing the review requirement would also remove review protection from
human-authored and non-Renovate pull requests. That is out of scope.

## Design

Add the MergeRaptor GitHub App, and no users or teams, to `main`'s
`bypass_pull_request_allowances.apps` branch-protection setting.

Use the app's installation token in the direct-merge workflow. The workflow
must merge only when all of these conditions hold:

1. The pull request author is `app/mergeraptor` or `renovate[bot]`.
2. Renovate has enabled auto-merge for that pull request. This preserves the
   existing `renovate.json` allowlist of digest, pin, patch, and minor updates.
3. Every check in the pull request's check rollup has completed successfully.

The workflow must report a failed merge command rather than converting it to a
success-shaped warning. It may exit successfully only when no qualifying pull
request exists for the completed workflow's head SHA.

## Components

### Branch protection

Retain the existing one-approval and CODEOWNERS requirements. Add only the
MergeRaptor GitHub App as a bypass actor. This permits an app-token direct
merge after the workflow's checks, but does not allow ordinary users,
`github-actions[bot]`, or unrelated GitHub Apps to bypass review.

GitHub documents this field as
`required_pull_request_reviews.bypass_pull_request_allowances.apps` in the
protected-branch API.

### Auto-merge caller

Add a caller for `reusable-renovate-automerge.yml` on completed PR CI
workflows. It passes the MergeRaptor app credentials already supported by the
reusable workflow and explicitly sets `base_branch: main`.

The reusable workflow inspects the associated pull request before merging,
rather than treating a single completed workflow as proof that all required
checks passed. Repeated completion events are safe: after the first successful
merge, later events find no open matching pull request.

## Error Handling

- A pull request with a pending, failed, cancelled, skipped, or missing check
  is not merged.
- An ineligible Renovate update (including a major version) is not merged
  because Renovate did not enable auto-merge.
- A denied or failed merge is a workflow failure with the GitHub CLI error
  retained in the log.

## Verification

1. Confirm the app appears as the sole bypass actor in `main` protection.
2. Open a qualifying Renovate dependency update and confirm it merges only
   after all checks pass, without a human review.
3. Confirm a human-authored PR remains blocked without a CODEOWNERS approval.
4. Confirm a major Renovate update remains open without automatic merging.

## Source

GitHub protected-branch REST API documentation:
https://docs.github.com/en/rest/branches/branch-protection?apiVersion=2022-11-28#update-branch-protection
