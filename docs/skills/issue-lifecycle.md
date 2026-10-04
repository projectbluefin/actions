---
name: issue-lifecycle
description: Use when onboarding a repository to issue-lifecycle, changing catalog-bound transitions, migrating label aliases, or diagnosing maintainer provenance and reporter notification behavior.
metadata:
  type: procedure
  context7-sources:
    - /websites/github_en_actions
    - /websites/github_en_rest
---

# Catalog-bound issue lifecycle

## When to Use

Use for the shared `issue-lifecycle/action.yml` action, its Python policy engine,
and a consuming repository's `.github/issue-policy.json`. The renderer in
`scripts/issue_status.py` owns Markdown and semantic reporter-action metadata;
`scripts/issue_policy.py` alone owns stage authorization and lifecycle writes.

## When NOT to Use

Use the separate Prow integration for authorized descriptive labels and negative
hold controls. Native PR review, checks, assignment, and merge controls remain
repository-owned. Lifecycle acceptance is not assignment or merge permission.

## Core Process

1. Read the target repository's authority and catalog before changing its caller.
   Supply `repository`, `display_name`, unique `comment_marker`,
   `delivery.type` (`image` or `release`), the five canonical `stages`, `labels`,
   `retired_stages`, `standing_issues`, and explicit `label_aliases`.
   `bug_fields` and `feature_fields` declare the repository's required form
   headings; application intake must not inherit another consumer's field names.
   Alias values are canonical `kind/*` or `area/*` names, or `null` for an
   explicitly approved discard. Alias migration cannot grant a stage or remove
   an independent gate, `agent/*`, or `hive/*` routing label. Keep source-backed
   operational reader labels until their consumers have actually cut over.
   Optional `kind_sources` maps an existing operational reader label to a
   canonical `kind/*` classification when no canonical kind exists. It never
   adds mirrored operational labels or grants acceptance. Optional `gate_labels`
   names actual independent reader denials, such as `question`; acceptance never
   clears them. Optional `prior_comment_markers` lists known historical lifecycle
   markers for transferred issues so only trusted Bot status comments can be
   reused under the new repository's marker.
   Optional `intake_rules` are caller-owned descriptive data, not a shared
   application's title/provenance assumptions. Each rule has `match` groups
   (`title_prefixes`, `body_contains`, `body_headings`) and `labels`; groups
   combine with AND and their literal values with OR, case-insensitively.
   Matching reads at most 512 title and 65,536 body characters, without arbitrary
   regex execution. Targets must exist in that catalog and cannot be lifecycle,
   consent, dispatch, review, hold or other protected controls. Existing primary
   kinds win; multiple inferred kinds retain classification/human gates. Metadata
   never authenticates a filing agent, grants acceptance or assigns work.
   Catalog `gate_labels` are also protected targets: an unchanged title must not
   re-create a native question/denial after its real owner explicitly withdraws it.
2. Prefer the shared `reusable-issue-lifecycle.yml@v1` conductor from a thin
   local caller: it checks out the trusted default branch without persisting
   credentials, serializes Prow before lifecycle, repairs after Prow failure,
   and uploads previews/archives. Direct incident callers use
   `projectbluefin/actions/issue-lifecycle@v1` explicitly because workflow-token
   issue writes do not trigger another workflow. The composite's optional
   `workspace` is for candidate data checkouts in read-only consumer previews;
   production writes retain default-branch/caller/source verification.
3. Preview from the Actions source root:

   ```bash
   python3 -m scripts.issue_policy --workspace /path/to/caller --catalog .github/issue-policy.json --dry-run --output /path/to/preview.json
   ```

   The catalog binds all writes to its repository; `--repo`, if supplied, must
   match. Snapshots are read-only and cannot be combined with `--apply`.
4. Merge and release the policy before enabling `apply: 'true'`. Every apply
   verifies the caller workflow ref and revision against its default branch,
   its checked-out workflow and catalog bytes, and the actual runtime, renderer,
   and composite bytes against the released Actions `v1` revision. Both caller
   and action revisions must be merged ancestors of their default branches.
   A feature-branch action or changed catalog is preview-only. The composite
   supplies `github.token` directly: local user-token applies are refused.
   The catalog's `main_ci_workflows` lists repository-owned native CI workflow
   paths. Apply also requires their latest push/manual runs at the actual current
   default-branch commit to be completed successfully, and requires Actions
   unit-tests/actionlint success at the released runtime commit. Missing, pending,
   skipped or failed runs fail closed. Grant caller `actions: read` for this check;
   no new token is needed. Keep main triggers unfiltered or dispatch the actual
   CI workflow at that main commit before activation. Prow runs the same guard
   before any command or result write.
5. Run a reviewed `migrate: 'true'` preview, then dispatch its apply through the
   merged caller. Migration covers open and closed issues and PRs by default.
   It preserves negative preferences, independent routing gates, and existing
   work. Before any migration/retirement write, the engine archives all issue/PR
   records, label definitions, the catalog, and preview. Upload the composite's
   `backup-directory` output even on failure. `migrate` and `labels-only` are
   quiet: no comments, reporter mentions, or closure.
   Quiet collection reuses the complete live listing for closed issues and PRs,
   whose label plans need no grants/reviews. Open real issues still read full
   authorization, edit and reply history; every actual write re-reads freshness.
   No-op quiet plans do not require an application GET. This avoids exhausting
   workflow-token requests on irrelevant historical facts without excluding
   closed records. Retirement is also labels-only: definition cleanup cannot
   mass-notify or close reports.
6. Retire definitions only after client cutover, with both `retire-labels` and
   `confirm-client-cutover` enabled. The engine checks all history, including
   closed PRs, for remaining retired and alias assignments before deletion.
   Retain archives and inspect stale-record failures before another dispatch.

### Transition and notification invariants

- Select trusted human events **before** selecting the latest grant. Bot label
  restoration is projection, not a new approval, delivery decision, or request.
  Subsequent human withdrawals, scope edits (including equal timestamps), and
  assessment/information resets invalidate stale delivery decisions.
- Acceptance requires a trusted human with write/maintain/admin permission and
  readable scope-edit history. Numbered queues and arbitrary merged `Refs`
  links never create acceptance or prove delivery. A maintainer selects
  `awaiting-release` after assessing the actual merged fix.
- Image receipts require `Image: ...@sha256:<64 hex>`, `Fix revision: <40 hex>`,
  `Release/build: https://...`, and `Verify: ...`. Application release receipts
  require `Package`, `Version`, and the same revision, release/build, and verify
  fields. Publication must reach the user's installation, including required
  image-installed helpers; a green skipped-publish run is not delivery.
- A trusted human records the receipt and selects `needs-verification`.
  Only the original human reporter's ordinary `Confirmed fixed` or
  `Still broken` reply after that authorized request can confirm or reject it.
  Later Bot projection events do not move the reply cutoff.
- Renderer output is `{comment, notify_reporter, notification_action}`. The
  runtime combines the semantic action with the authorized request identity,
  repository, and issue number for mention deduplication. Never parse Markdown
  headings or prose to decide notification eligibility. A first status can
  notify directly; changing an existing status uses one separate targeted
  notification only for a genuinely new action.
   A free-form information request requires a trusted human's explicit `@reporter`
   question after the information selection, or that selecting human's question
   within five minutes before it (ask-then-picker pairing). Older, answered or
   maintainer-directed questions cannot mint a reporter action.
   If the requester/recipient is unclear, the next action stays with the maintainer.
- Stale body, label, URL/repository, or timestamp changes abandon that record
  instead of overwriting it. Install new negative gates before removing old
  queue assignments. Human comments and forged lifecycle markers are never
  edited; only `github-actions[bot]` status/history comments are reusable.
  Transferred machine statuses with explicitly cataloged historical markers are
  reused instead of reposted. If several authorized statuses coexist, retain one
  active report and collapse the others into clearly superseded, preserved
  automated history; human or other-app lookalikes remain untouched.
- PRs have no issue-stage labels, including closed history, and lifecycle never
  manufactures reviews, approvals, assignments, or merge state. Unresolved kind
  conflicts retain their descriptors and classification/human gates until a
  trusted human explicitly selects one kind. Conflicting operational kind
  sources retain their original reader labels and require classification rather
   than guessing a canonical kind. Explicit structured/title intake seeds only
   catalog-declared descriptive metadata, never acceptance or dispatch. Existing
   primary kinds win; unknown intake remains gated for classification.

### Read-only onboarding preview

Run `python3 scripts/check-issue-onboarding.py --workspace /path/to/caller --repository owner/repo`
from trusted Actions source; candidate forms/catalog/workflows are data only.
Consumers call `reusable-issue-policy-preview.yml@v1` with read-only contents,
issues and pull-requests permissions, no secrets. It records actual caller/runtime
commits and archives structural preflight plus the real runtime's `apply=false`
plans. During bootstrap only, a reviewed first-party candidate branch may supply
this preview interface/runtime; the fixed repository and read-only permissions
remain mandatory. Replace the preview interface with `@v1` after publication;
production callers always use `reusable-issue-lifecycle.yml@v1`.

## Common Rationalizations

- “The bot restored the label, so use its latest event.” Filter provenance first;
  otherwise valid human decisions and intervening reporter replies disappear.
- “The legacy queue or linked merge means approved/shipped.” Reconcile the
  explicit human grant and recorded delivery receipt instead.
- “Formatting changed; notify again.” Compare semantic action/request identity,
  not Markdown. Notifications are reporter obligations, not status decoration.
- “Retirement only needs an open-issue check.” Closed issue and PR assignments
  are historical data and must be migrated and archived as well.
- “Run apply locally to get migration done.” Use the merged caller's workflow
  token so automatic gates remain Bot-authored rather than human provenance.

## Red Flags

Unreviewed catalog bytes; feature workflow/action refs with write permissions;
consumer copies of the runtime; stage-writing Prow commands; alias mappings
into acceptance; inferred acceptance from a merge; rewritten human comments;
notifications keyed to prose; deleted definitions with remaining history;
unscoped API writes; discarded assignees, independent gates, or routing labels.

## Verification

After all integration edits land, run the repository's native checks and
`tests/test_issue_policy.py` plus `tests/test_issue_status.py`. Exercise a real
read-only workflow using each consuming catalog before reviewed activation.
Confirm rejected feature-ref writes, archive retention, quiet migrations,
all-history retirement, and no duplicate reporter mention after a formatting
change or Bot restoration. Publish CI evidence before enabling live writers.

Documentation sources: GitHub Actions [composite metadata](https://docs.github.com/en/actions/tutorials/create-actions/create-a-composite-action),
[contexts](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts),
and [workflow-token authentication](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token);
GitHub REST [commit comparisons](https://docs.github.com/en/rest/commits/commits#compare-two-commits)
and [repository contents](https://docs.github.com/en/rest/repos/contents#get-repository-content).
