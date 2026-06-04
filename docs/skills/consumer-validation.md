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
2. **Verify CI green**: Wait for the consumer PR's CI to pass completely
3. **Link in your PR**: Add the consumer PR URL to your PR description
4. **Merge actions first**: Merge this PR, then update the consumer PR to re-pin to the new `@v1` SHA

## Out-of-org consumers

For `aurora` and `bazzite`, you cannot open PRs directly. Verify that your change does not break the Justfile contract (recipe signatures listed in `docs/skills/consumer-guide.md`). If in doubt, ping `@castrojo` or `@hanthor`.

## Why this matters

The `@v1` tag is a floating pointer. A broken merge immediately breaks builds for ALL consumers with no rollback except a revert. The consumer validation step is the only gate.
