# Consumer Validation Protocol — projectbluefin/actions

Any change to this repo affects ALL consumers simultaneously via the `@v1` floating tag.

## Blast radius

| Consumer | Org | Notified? |
|---|---|---|
| `projectbluefin/bluefin` | projectbluefin | ✅ Direct access |
| `projectbluefin/bluefin-lts` | projectbluefin | ✅ Direct access |
| `ublue-os/aurora` | ublue-os (external) | ⚠️ No CI visibility |
| `ublue-os/bazzite` | ublue-os (external) | ⚠️ No CI visibility |

## Validation steps (required before merge)

1. **Pin a consumer PR**: Open a draft PR in `projectbluefin/bluefin` that pins its workflow to your branch SHA (not `@v1`):
   ```yaml
   uses: projectbluefin/actions/.github/workflows/reusable-build.yml@<your-branch-sha>
   ```
2. **Verify CI green**: Wait for the consumer PR's CI to pass completely.
3. **Fill the PR template evidence fields** in this repo:
   - `Consumer PR: https://github.com/projectbluefin/<consumer>/pull/<number>`
   - `Consumer CI run: https://github.com/projectbluefin/<consumer>/actions/runs/<id>`
   - `Out-of-org consumer impact: <why aurora/bazzite are safe, or N/A>`
4. **Keep the checklist honest**: Check the three consumer-validation boxes only after the linked PR and run exist.
5. **Merge actions first**: Merge this PR, then update the consumer PR to re-pin to the new `@v1` SHA.

## Automated PR check

`.github/workflows/consumer-validation.yml` makes the protocol harder to skip:

- It runs on PR open, sync, ready-for-review, and PR body edits.
- It only enforces the evidence fields when the PR changes `bootc-build/**/action.yml` or `.github/workflows/reusable-*.yml`.
- It fails if any required field is missing or in the wrong format.

**Bot/Renovate exemption:** PRs authored by a bot (login ending in `[bot]` or starting with `app/`, e.g. `renovate[bot]`, `mergeraptor[bot]`) are automatically exempt — they skip all three evidence checks. SHA pin bumps carry no behavior change and cannot provide consumer PR URLs.

**N/A rules — which fields accept it:**

| Field | Accepts "N/A"? | Requirement |
|---|---|---|
| `Consumer PR:` | ❌ No | Must be `https://github.com/projectbluefin/(bluefin\|bluefin-lts\|dakota)/pull/NNN` |
| `Consumer CI run:` | ❌ No | Must be `.../actions/runs/NNN` |
| `Out-of-org consumer impact:` | ✅ Yes | Any non-empty, non-`TODO`/`TBD` explanation (including "N/A — aurora/bazzite unaffected because...") |

Even for additive-only changes (new optional input with a safe default), you still need to open a draft consumer PR and get a CI run number. The consumer CI run URL is what proves the action was exercised in a real workflow.

**Cross-fork PRs:** External contributor PRs from forks need a maintainer to approve the pending workflow run before CI executes. Use:
```bash
gh api repos/projectbluefin/actions/actions/runs/<run-id>/approve -X POST
```

**After merging a fix to `consumer-validation.yml` itself:** `gh run rerun` re-executes the workflow from the HEAD branch's original commit — it ignores changes on `main`. To get a run using the updated workflow, push a new commit to the PR branch or admin-merge the PR directly.

Treat the check as evidence collection, not as a substitute for real validation. Fake links still violate policy and should be rejected in review.

## Out-of-org consumers

For `aurora` and `bazzite`, you cannot open PRs directly. Verify that your change does not break the Justfile contract (recipe signatures listed in `docs/skills/consumer-guide.md`) and summarize that reasoning in `Out-of-org consumer impact:`. If in doubt, ping `@castrojo` or `@hanthor`.

## Why this matters

The `@v1` tag is a floating pointer. A broken merge immediately breaks builds for ALL consumers with no rollback except a revert. The consumer validation step is the only gate.
