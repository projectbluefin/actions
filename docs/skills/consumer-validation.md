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
- It fails if the PR body is missing a consumer PR URL, a consumer CI run URL, or an out-of-org impact note.

Treat the check as evidence collection, not as a substitute for real validation. Fake links still violate policy and should be rejected in review.

## Out-of-org consumers

For `aurora` and `bazzite`, you cannot open PRs directly. Verify that your change does not break the Justfile contract (recipe signatures listed in `docs/skills/consumer-guide.md`) and summarize that reasoning in `Out-of-org consumer impact:`. If in doubt, ping `@castrojo` or `@hanthor`.

## Why this matters

The `@v1` tag is a floating pointer. A broken merge immediately breaks builds for ALL consumers with no rollback except a revert. The consumer validation step is the only gate.
