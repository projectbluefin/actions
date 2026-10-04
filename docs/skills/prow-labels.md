---
name: prow-labels
description: "Use when onboarding or operating the shared issue-only Prow maintainer controls, deriving safe configuration from a caller label catalog, or diagnosing a denied or partial command result."
metadata:
  type: procedure
  context7-sources:
    - /websites/github_en_actions
    - /websites/github_en_rest
---

# Constrained CNCF Prow issue controls

## When to Use

Use `prow-labels/action.yml` before the shared issue-lifecycle action in the same
serialized, trusted caller job. This is **actual CNCF Prow execution**, surrounded
by authorization, preflight, and API-observed reports. The Python controller never
adds or removes labels: the released upstream action owns those operations.

The artifact version and full immutable commit are recorded in the action's
`uses:` line. To upgrade, resolve the release's annotated tag to its **commit**
object, inspect the released source paths below, update the version comment and
SHA together, then exercise real upstream execution before deployment.

## When NOT to Use

- Do not install upstream's broad default workflow alongside this action. It
  enables assignment, reviews, testing/dispatch, and automatic PR merging.
- Do not invoke upstream Prow directly to bypass this authorization wrapper.
- Do not use Prow for lifecycle acceptance, delivery, verification, assignment,
  `needs-human` withdrawal, native reviews, or merging.
- Do not execute a pull-request checkout with a write token or supply a user token.
- Do not enable upstream `/help`: it **adds `help wanted`**, rather than explaining
  commands. Informational help below is a wrapper control, not an invented Prow
  capability.

## Core Process

### Trusted caller inputs

The composite takes:

| Input | Contract |
| --- | --- |
| `github-token` | The caller's `GITHUB_TOKEN`; `issues: write`, `contents: read`, `actions: read` |
| `catalog` | Absolute path to the trusted default-branch `.github/issue-policy.json` |
| `catalog-path` | Repository catalog path; defaults to `.github/issue-policy.json` |

The current default-branch catalog must exactly match the checked-out catalog.
Repository name must match both `GITHUB_REPOSITORY` and the immutable event.
The released lifecycle deployment guard checks trusted caller/source bytes and
actual target/released main CI before any Prow command or feedback write.
Use only `issue_comment: created` to execute commands. Other events skip Prow.
Use repository-scoped caller concurrency with `cancel-in-progress: false`, and
run lifecycle reconciliation **after** Prow, including when Prow execution fails.
`GITHUB_TOKEN` label writes do not emit the downstream label workflow events that
would otherwise perform this reconciliation.

The caller must check out only trusted default-branch files, retain the original
`GITHUB_EVENT_PATH`, and grant **no** `actions`, `statuses`, or `pull-requests`
write permissions merely for this action. No Prow jobs are enabled. The action
requires upstream's Node 24-capable runner (self-hosted runner 2.327.1 or newer).

### Catalog-derived upstream configuration

Create `.github/prow.yaml` on the caller's default branch, using **JSON syntax**
(JSON is valid YAML). Its contents must equal
`scripts.prow_commands.expected_config(catalog)`; list ordering does not matter.
This single source derives both Prow values and the wrapper whitelist/cardinality:

```json
{
  "labels": {
    "kind": {"values": ["bug", "feature", "task"], "exclusive": true},
    "area": {"values": ["api", "docs"], "exclusive": false}
  },
  "hold": {"label": "hold"},
  "tide": {"merge_on_events": false},
  "require_matching_label": []
}
```

List **all and only managed** suffixes from the caller's `labels` entries under
`kind/*` and `area/*`; omit `area` if there are none. Catalog `protected_labels`
are unmanaged and never command values. Values must be lower-case command tokens.
Kind is exclusive, area is not. No extra plugins/configuration are allowed.
Label names must be unique case-insensitively; lifecycle/retired stages cannot
occupy `kind/*` or `area/*`. Include `hold` in the catalog to enable hold controls.
Seed actual repository label definitions from the reviewed caller catalog before
activation; Prow's broad `label-sync` job is not part of this action.

The controller verifies this file at the default-branch commit and supplies that
immutable file as upstream's explicit `config` source. That input replaces the
organization configuration tier. **Upstream still overlays the repository's
current default-branch `.github/prow.yaml`**; the maintained default branch is a
trusted policy input, not a comment-controlled source. Change this file and its
catalog together. Upstream cannot consume a local config file.

### Supported controls

Post exactly **one command-only line per new comment**; no prose, code block,
second command, extra value, or unknown value. Command/value case is accepted
case-insensitively. Requests are validated against the full original comment;
no rewritten/fabricated event is passed to upstream.

| Control | Actual effect |
| --- | --- |
| `/kind VALUE` | Upstream replaces existing `kind/*` with one managed catalog kind; refused if a protected operational `kind/*` is present |
| `/area VALUE` | Upstream adds one catalog area; existing areas remain |
| `/remove-area VALUE` | Upstream removes that catalog area only |
| `/hold` | Upstream adds literal `hold`; maintainer records why and the condition to resume |
| `/hold cancel`, `/unhold`, `/remove-hold` | Upstream withdraws literal `hold` only |
| `/help`, `/prow help` | Wrapper explains controls; no upstream execution or label changes |

All label controls require the immutable human commenter to match the event
sender and have **current** `write`, `maintain`, or `admin` repository permission
from `GET /repos/{owner}/{repo}/collaborators/{username}/permission`. Organization
membership, `author_association`, a prior grant, and comment prose are not authority.
The live comment's actor, body, and revision must still match the immutable event.
Help is available without label permission. Bots and mismatched actors cannot
execute controls. Label controls apply to **open issues only**; PR attempts are
denied with native PR instructions.

Upstream exclusivity removes **every** other `kind/*`, not just configured values.
Before invoking it, preflight reads current labels and denies `/kind` if it would
remove a catalog-protected operational kind, including case variants. This is a
no-execution denial, not an acceptable partial mutation. Use GitHub's **Labels**
picker to select the requested managed kind and deselect only other managed
primary kinds; leave protected operational signals and independent labels
unchanged. Confirm any operational signal change with its Hive operator first.
For example, ordinary debt can use `/kind debt`/`kind/debt` only when no protected
kind is present; `/kind tech-debt` cannot assign protected `kind/tech-debt`.

There is deliberately no `/remove-kind`: an open issue requires exactly one kind.
Multiple kinds in one comment are rejected even though upstream accepts them.
Generic `/label`, `/remove`, stage commands, approval/LGTM, assignment/reviews,
test/dispatch, and required-label commands are never enabled. Selecting a kind or
withdrawing hold does not grant implementation acceptance. `blocked`, `human-only`,
independent `needs-human`, and `do-not-merge/*` labels are never part of the allowed
removal set. A maintainer's `/hold cancel` is an explicit withdrawal of that issue's
`hold` pause, not permission to clear any other owner's negative gate.

### Direct results and partial failures

Every request outcome is rendered by `scripts.issue_status.prow_report` and posted
as one new result comment. It includes the command, status, observed labels,
maintainer controls/next steps, and explicit reporter action. Ordinary reporters
never need slash commands or label permissions.
Untrusted command and label text stays inside single-line inert Markdown code
spans, even with embedded backticks/headings/mentions. Command display is a
bounded 512-character excerpt; authorization and upstream still consume the
original unmodified comment. Quoted feedback is not a delivered lifecycle
notification marker.

Keep bot text short and plain: **Status**, role headings with short action
bullets, then **Reporter action**. Say what to do next, not why the system is
built that way. Change display strings only; never change the payloads passed to
`_action()` in `issue_status.py`. Those are the reporter notification dedup keys,
and changing them re-pings every reporter with an open request.

Renderer result schema:

```text
command: original requested command
outcome: applied | denied | invalid | help
changes: {add: [observed labels], remove: [observed labels]}
reason: specific permission/scope/error/postcondition explanation
next_steps: [concrete controls]
supported_commands: [syntax and allowed catalog values]
changes_unknown: true only when the post-execution API read failed
pull_request: true for PR-targeted feedback
```

The finalizer reads actual issue labels after upstream execution and compares the
**entire** label set to the allowed postcondition. Exit zero without the expected
transition is an error. An already-satisfied state is reported as an observed
no-op, not a new transition. Unexpected independent-gate loss is an error, never
an applied result. The composite exposes `outcome` (empty for ordinary discussion).

Upstream removes stale kinds **before** checking/adding the new definition. Preflight
therefore checks actual definitions before execution. An API failure can still
leave partial changes: report the observed delta without claiming rollback or
success. If the post-read fails, report **unknown mutation**, not "nothing changed."
Execution/postcondition failures fail the composite after reporting; callers must
still reconcile lifecycle/classification. A report API write is confirmed from
GitHub's returned comment, not presumed successful. If GitHub refuses the report,
the run fails explicitly; inspect the run/current labels before retrying.

### Primary source capability evidence

Context7 resolves the GitHub Actions and GitHub REST API IDs listed above, but did
not provide a matching library for `cncf/prow-github-actions`. Use the **released**
upstream files at the action's pinned commit, not documentation on `main`:

- [`action.yml`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/action.yml):
  `node24`, `prow-commands`, `config`, `jobs`; no command outcome outputs.
- [`docs/commands.md`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/docs/commands.md):
  label/hold policy is anyone upstream; aliases enable their whole family;
  `/help` labels; label writes trigger required-label and Tide evaluation.
- [`src/labels/prefixed.ts`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/src/labels/prefixed.ts):
  exclusive removal before add, ignored unknown values, multiple requested values.
- [`src/labels/hold.ts`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/src/labels/hold.ts):
  cancel removes the configured hold and legacy `hold`; choosing literal `hold`
  confines removal to one negative overlay.
- [`src/issueComment/handleIssueComment.ts`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/src/issueComment/handleIssueComment.ts):
  command family dispatch and unconditional post-label sweep.
- [`src/plugins/tide.ts`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/src/plugins/tide.ts):
  `tideOnComment` skips real issues before a PR API call. **Issue-only execution is
  the merge authority boundary**, not just `tide.merge_on_events: false`.
- [`src/plugins/requireMatchingLabel.ts`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/src/plugins/requireMatchingLabel.ts):
  empty `require_matching_label` returns before label/comment API operations;
  the subject is the event's individual issue/PR, not a repository-wide sweep.
- [`src/run.ts`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/src/run.ts):
  `issue_comment` dispatches only its comment handler, never cron jobs or a
  repository-wide PR sweep.
- [`src/utils/config.ts`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/src/utils/config.ts):
  explicit-source replacement of org tier and default-branch repo overlay.
- [`src/utils/labeling.ts`](https://github.com/cncf/prow-github-actions/blob/v3.0.1/src/utils/labeling.ts):
  definitions must exist; labels compare case-insensitively.

## Common Rationalizations

| Temptation | Correct response |
| --- | --- |
| "Upstream authenticates maintainers." | Its descriptive/hold commands allow anyone; keep live wrapper permission checks. |
| "Exclusive kind means one kind per comment." | It preserves every requested kind; reject more than one value/command before invocation. |
| "Disabling event merging makes PR commands safe." | Comment sweep can evaluate PR merging; deny every PR execution. |
| "`/help` is harmless information." | Upstream labels help-wanted; intercept informational help without invoking it. |
| "A green step proves success." | Read actual API outcomes and expected labels; partial/no-op/unknown changes differ. |

## Red Flags

An upstream workflow/default job, floating third-party tag, generic remove/label
command, non-human authority, untrusted checkout, extra required-label plugin,
nonliteral hold target, an independently running stage writer, or a report that
claims success/no mutation without an API observation.

## Verification

After integration, the main owner runs permanent wrapper behavior tests in
`tests/test_prow_commands.py`, renderer tests, native action/YAML gates, and real
released-artifact consumer workflow execution. Unit API fixtures test authorization,
scope, cardinality, failures, and observable transitions; they do **not** prove the
upstream bundle executed. The deployment proof must include a maintainer command,
rejected unauthorized/stage/PR requests, actual label changes and result comments,
and an ordinary reporter reply through the single serialized lifecycle path.
