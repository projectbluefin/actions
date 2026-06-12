---
name: composite-actions
description: Authors, modifies, and debugs composite GitHub Actions in projectbluefin/actions. Covers action structure, SHA pinning, shell best practices, rollout strategy, CI-fix-first workflow, and known workarounds. For full action-by-action details see composite-actions/action-reference.md; for reusable workflow details see composite-actions/reusable-workflow.md.
metadata:
  type: reference
---

# Composite Actions - Authoring Skill

Reference for writing and maintaining composite GitHub Actions in this repo.

**Update this file** when you discover a new pattern, workaround, or convention - in the same PR as your change.

## Contents
- [Structure](#structure)
- [SHA Pinning](#sha-pinning)
- [Shell steps](#shell-steps)
- [Action catalog](#action-catalog)
- [Rollout strategy](#rollout-strategy)
- [Adding a new action](#adding-a-new-action)
- [Common editing pitfalls](#common-editing-pitfalls)
- [CI-fix-first workflow (for agents)](#ci-fix-first-workflow-for-agents)
- [Known workarounds](#known-workarounds)

**Sub-files (load as needed):**
- [`composite-actions/action-reference.md`](composite-actions/action-reference.md) - full action-by-action reference
- [`composite-actions/reusable-workflow.md`](composite-actions/reusable-workflow.md) - reusable-build.yml and reusable-release.yml details

---

## Structure

Every action lives at `bootc-build/<name>/action.yml`. No build system, no scripting layer - only YAML + inline shell.

Required top-level keys:

```yaml
name: "bootc-build/<name>"
description: "One-line summary"
author: "projectbluefin"
inputs: { ... }
outputs: { ... }      # omit if no outputs
runs:
  using: "composite"
  steps: [ ... ]
```

---

## SHA Pinning

**Third-party actions** (anything outside `projectbluefin/`) must be pinned to a full commit SHA with a version comment:

```yaml
uses: sigstore/cosign-installer@7e8b541eb2e61bf99390e1afd4be13a184e9ebc5 # v3.10.1
```

Never use floating tags (`@main`, `@v3`, `@latest`) on third-party actions. Renovate runs in **this repo** and auto-merges SHA pin and digest bumps when CI passes.

The version comment must match a **released** version tag (e.g. `v3.10.1`, not just `v3`). If a repo has no releases or tags, use a descriptive comment instead:

```yaml
uses: ublue-os/some-action@abc123def456... # no-release, Merge PR #18 (2026-02)
```

**First-party actions** (anything inside `projectbluefin/actions`) use `@v1` - never SHA-pin your own code:

```yaml
# Correct
uses: projectbluefin/actions/bootc-build/create-release@v1
uses: projectbluefin/actions/.github/workflows/reusable-release-gate.yml@v1

# Wrong - stale SHA pins on first-party code cause silent failures
uses: projectbluefin/actions/bootc-build/create-release@abc1234... # v1
```

SHA pinning is a third-party supply-chain defence (prevents tag hijacking on external repos you don't control). It does not apply to code you own.

---

## Shell steps

### Error handling

Start every non-trivial shell step with:
```bash
set -euo pipefail
```

Use `set -eux` for steps where verbose trace output aids debugging (e.g., package installs).

### Passing inputs to shell

Pass inputs through the `env:` block - do not expand `${{ inputs.foo }}` inline inside `run:` scripts:

```yaml
# ✅ correct
env:
  IMAGE: ${{ inputs.image }}
  DIGEST: ${{ inputs.digest }}
run: |
  cosign sign -y "${IMAGE}@${DIGEST}"

# ❌ wrong - shell injection risk, harder to trace
run: |
  cosign sign -y "${{ inputs.image }}@${{ inputs.digest }}"
```

This applies to **all** expression types in `run:` blocks: inputs, matrix values, context values (`github.actor`, `github.event_name`), step outputs, and especially secrets. The only safe place to reference `${{ ... }}` in shell is via env vars.

**Glob inputs:** when an input is a shell glob (e.g. `shellcheck-glob`), pass it via env and expand it unquoted:

```yaml
env:
  SHELLCHECK_GLOB: ${{ inputs.shellcheck-glob }}
run: |
  shopt -s globstar nullglob
  # shellcheck disable=SC2086
  shellcheck ${SHELLCHECK_GLOB}
```

Word splitting on an env var is safe for globs but is NOT command injection - `;` in a variable is not a command separator.

### Secrets in run: steps

Pass secrets via `env:` and reference with `${VAR}`:

```yaml
env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
run: |
  echo "${GITHUB_TOKEN}" | podman login ...
```

Never do `echo ${{ secrets.GITHUB_TOKEN }}` directly in `run:`. GitHub masks it in logs but error messages and downstream uses may still leak it.

### Lowercasing registry paths

Registry/org names must be lowercased before any push or reference:

```bash
REGISTRY_LOWER="${REGISTRY,,}/${GITHUB_REPOSITORY_OWNER,,}"
```

### Privileged operations

Container/storage commands that need root use `sudo -E` to preserve the environment:

```bash
sudo -E podman push ...
```

---

## `github-token` pattern

Actions that need registry access or GitHub API calls take an explicit `github-token` input (required). The calling workflow supplies `${{ secrets.GITHUB_TOKEN }}` or a PAT - the action never uses it implicitly.

```yaml
inputs:
  github-token:
    description: "Token for registry login"
    required: true
```

---

## Failing fast with `::error::`

Surface actionable errors using the `::error::` workflow command before `exit 1`:

```bash
echo "::error::signing-mode=keyless requires 'id-token: write' permission in the calling job."
exit 1
```

---

## Action catalog

Quick reference - for full details see [`composite-actions/action-reference.md`](composite-actions/action-reference.md).

| Action | Purpose |
|---|---|
| `setup-runner` | Update podman, mount BTRFS storage, install tools |
| `dnf-cache` | Restore/save buildah layer cache |
| `preflight` | Validate registry auth, normalize image refs |
| `push-image` | Push with retry, digest capture, skopeo alias tags |
| `sign-and-publish` | Cosign keyless/key + Syft SBOM + SLSA provenance attestation |
| `apply-pkg-intervals` | Set `user.update-interval` xattrs on RPM files — run before `chunka` |
| `chunka` | OCI-native chunkah v0.6.0 rechunking - the single rechunk implementation for all Fedora-based images |
| `ghcr-cleanup` | Prune old/untagged GHCR images |
| `detect-changes` | Detect changed paths, compute image-flavor build matrix |
| `validate-pr` | Run just check, shellcheck, hadolint, pre-commit |
| `scan-image` | Trivy CVE scan before push, SARIF upload, optional CVE issue creation |
| `generate-tags` | Generate Bluefin/Fedora OCI alias tags (Path 2 only) |
| `create-manifest` | Multi-arch OCI manifest index assembly |
| `generate-release-notes` | git-cliff Conventional Commits changelog |
| `create-release` | Factory-standard release: SBOM diff + release card + supply chain notes |
| `validate-pr-title` | Enforce Conventional Commits PR title format |

---

## Rollout strategy

### Additive-only rule

All changes to existing actions must be **additive**: new optional inputs with defaults that preserve existing behavior. Never remove or rename an input, and never change the behavior an existing caller already relies on, without a major version bump.

Valid additive change:
```yaml
# Adding a new optional input with a safe default
force-compression:
  description: "Force recompression on push"
  default: "false"   # ← existing callers are unaffected
```

Invalid (breaking) change: removing `tags`, renaming `github-token`, or changing a default that alters behavior for existing callers.

### Force-compression input rationale

The `chunka` and `push-image` actions expose an optional `force-compression` input (default: `false`). This input exists for CentOS Stream 10 and other non-Fedora consumers that need to migrate existing registry layers from `gzip` to `zstd:chunked`. Fedora consumers should leave it at the default because Fedora images are already `zstd:chunked` and forcing recompression strips `ostree.components` layer annotations.

### Package cadence intervals (apply-pkg-intervals + reusable-pkg-cadence)

`bootc-build/apply-pkg-intervals` is wired into `reusable-build.yml` between the build and rechunk steps. It sets `user.update-interval` xattrs on every RPM-owned file so chunkah can group packages by how often they actually update. A typical weekly update then only pulls layers containing that week's changed packages — not fonts, firmware, or other stable content that shares layers separately.

**Zero-config for existing consumers:** the action silently no-ops if `files/pkg-intervals.tsv` doesn't exist in the consumer repo. No Containerfile changes are needed.

**Adopting as a new consumer:**

1. Add `.github/workflows/pkg-cadence.yml` to your repo:

```yaml
# Trigger on your stable-push/release workflow completing — not a cron.
# This ensures you measure exactly the image users just received.
on:
  workflow_run:
    workflows: ["Execute Release"]   # replace with your stable-push workflow name
    types: [completed]
  workflow_dispatch:
    inputs:
      force_reclassify:
        type: boolean
        default: false

permissions: {}

jobs:
  cadence:
    if: github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success'
    uses: projectbluefin/actions/.github/workflows/reusable-pkg-cadence.yml@v1
    with:
      image: ghcr.io/yourorg/yourimage:stable
      repo: yourorg/yourimage
      force_reclassify: ${{ inputs.force_reclassify || false }}
    secrets: inherit
```

2. Run the workflow once manually (`workflow_dispatch`) to bootstrap `files/pkg-intervals.tsv`. It commits directly to `main`.

3. From that point, `apply-pkg-intervals` runs automatically on every non-PR, non-testing build via `reusable-build.yml`, and the cadence workflow self-updates after each release.

4. After ~4 weeks, bootstrap heuristics are replaced by observed churn data automatically.

**Bootstrap heuristics** (used for the first 4 weeks):

| Pattern | Interval |
|---|---|
| `tailscale`, `bootc`, `distrobox`, `fastfetch`, `uupd` | `weekly` |
| `*-fonts*`, `google-noto-*`, `liberation-*`, `*cantarell*` | `yearly` |
| `*firmware*`, `alsa-*-firmware` | `quarterly` |
| everything else | `monthly` |

**Threshold calibration** (90-day window, weekly stable builds ≈ 13 builds):

| Changes in window | Interval |
|---|---|
| ≥ 8 | `weekly` |
| 2–7 | `monthly` |
| 1 | `quarterly` |
| 0 | `yearly` |

If your build cadence differs from weekly, pass `force_reclassify: true` after adjusting the thresholds in the reusable workflow, or open an issue to add a `build_cadence` input.

### Breaking change policy

If a breaking change is unavoidable:
- Option A: create a versioned subdirectory (`bootc-build/<name>/v2/action.yml`) and route new callers there while old callers keep `v1`
- Option B: coordinate a single wave - update all consuming repos in one PR sweep, then bump `@v1`

Document the blast radius (which repos, which inputs change) in the PR description. Do not merge without a link to passing CI in at least one consumer.

See [`consumer-validation.md`](consumer-validation.md) for the required before-merge protocol.

---

## Adding a new action

1. Create `bootc-build/<name>/action.yml`.
2. Pin all external `uses:` to commit SHAs with version comments.
3. Use the `env:` block pattern for all inputs passed to shell.
4. If the action downloads or references any external file (Containerfile, script, config) at runtime, vendor it or verify its SHA-256 - see `docs/skills/supply-chain.md`.
5. Add the action to the table in `README.md`.
6. Add a row to the skill routing table in `docs/SKILL.md`.
7. Add an entry to [`composite-actions/action-reference.md`](composite-actions/action-reference.md).
8. Add the action to the catalog table in `docs/skills/consumer-guide.md`.

---

## Common editing pitfalls

### Dropping `with:` when editing `uses:`

When you change only the SHA or comment on a `uses:` line, it's easy to accidentally delete the `with:` block below it. The result is a valid-looking YAML step where `uses:` runs but all inputs are silently dropped - actionlint catches this on push.

```yaml
# ❌ broken - with: block dropped, all inputs silently gone
- name: Upload artifact
  uses: actions/upload-artifact@abc123 # v7.0.1
    path: /tmp/output/               # ← this is now orphaned YAML, not under with:

# ✅ correct
- name: Upload artifact
  uses: actions/upload-artifact@abc123 # v7.0.1
  with:
    path: /tmp/output/
```

Always verify the `with:` block is still present after editing a `uses:` line. Actionlint enforces this but only on push - not in local editors.

### Multi-line strings in `run:` blocks

A double-quoted multi-line string inside a YAML `run:` block breaks shellcheck (and therefore
actionlint). The newlines inside the YAML block scalar cause the parser to see subsequent lines as
stray YAML keys rather than shell string content.

```yaml
# ❌ broken - shellcheck sees an unclosed double-quoted string
- run: |
    git commit -m "subject line

Assisted-by: foo
Co-authored-by: bar"   # actionlint: SC1072 / SC1073 / unexpected YAML key

# ✅ correct - use ANSI-C quoting ($'...') to embed newlines
- run: |
    msg="subject line"$'\n\n'"Assisted-by: foo"$'\n'"Co-authored-by: bar"
    git commit -m "${msg}"
```

Use `$'...\n...'` concatenation whenever a shell string must contain literal newlines inside a
YAML block scalar. Heredocs are also acceptable for longer messages.

---

## CI-fix-first workflow (for agents)

When an agent working in a **consuming repo** (bluefin, aurora, bazzite...) discovers a CI issue that involves duplicated inline steps or pinned third-party actions, the fix belongs **here first**:

1. **Check if an action already exists** — scan the catalog above. If the shared action doesn’t exist yet, create it here (follow “Adding a new action” above).
2. **Open a PR in this repo** on a feature branch with the new or updated action.
3. **Open a draft PR in the consumer repo** using `@v1` references (no SHA pinning needed). CI must pass there before this repo’s PR merges.
4. **Merge this repo’s PR**, then advance `@v1` to the new main HEAD (see `@v1` runbook in AGENTS.md). Consumer repos pick up the change automatically on their next workflow run.

**What belongs here vs. in the consumer repo:**

| Belongs here (`projectbluefin/actions`) | Stays in the consumer repo |
|---|---|
| Shared step sequences (lint, validate, detect-changes) | Caller-specific permissions scoping |
| Third-party action pins (hadolint, install-action, paths-filter) | `secrets: inherit` decisions |
| Reusable logic used in ≥2 workflows or repos | Repo-specific Justfile recipes |
| Path-filter definitions shared across workflows | Workflow scheduling and triggers |

Never add a new inline `uses:` for a third-party action in a consumer workflow if that action is already wrapped here. Inline pins create Renovate drift across all consumer workflows - centralize them.

---

## Known workarounds

| Workaround | Location | Issue |
|---|---|---|
| `chown /run/user/$UID/containers` before login | `push-image`, `create-manifest` | Earlier `sudo podman login` can leave root-owned auth files that break later user-space login |

## Trigger patterns

**Never use a cron to run a workflow that depends on another workflow completing.** Crons embed a timing assumption that drifts and creates silent races. Use `workflow_run` with a `conclusion == 'success'` guard instead:

```yaml
on:
  workflow_run:
    workflows: ["Execute Release"]
    types: [completed]
jobs:
  my-job:
    if: github.event.workflow_run.conclusion == 'success'
```

Always add `workflow_dispatch` alongside `workflow_run` so the workflow can be triggered manually without waiting for the upstream workflow to run.
| `chmod 777` before cache save | `dnf-cache` | [actions/cache#1533](https://github.com/actions/cache/issues/1533) - root-owned files break cache agent |
| `chown ~/.sigstore` before cosign | `sign-and-publish` | Runner sigstore cache created with wrong ownership |
| podman upgraded from Ubuntu resolute | `setup-runner` | Ubuntu 24.04 podman too old for `ostree.components` annotations + `zstd:chunked` push |
| `-v $(pwd):/run/src` + `--security-opt=label=disable` | `chunka` | buildah < v1.44 drops bind-mounts without these; needed for the OCI output dir (`out/`) to survive to the final stage |
| `sudo rm -rf out` | `chunka` | Containerfile.splitter leaves `out/` dir in CWD (v0.6.0+; was `out.ociarchive` in v0.5.0); stale dir breaks re-runs |
| `sudo podman save \| podman load` | `chunka` | buildah (root) and podman (user) use separate container stores |

### Reusable workflow caller permissions ceiling

GitHub enforces the caller's `permissions:` block as a hard ceiling for every callee job. A callee
job declaring `contents: write` is **silently downgraded** to `contents: read` if the caller only
grants `contents: read`.

**Pattern:** audit the caller's top-level `permissions:` block against every job the callee
declares, and ensure the caller grants the union of all permissions any callee job requires.

```yaml
# lifecycle-caller.yml: ceiling must include write because on-pr-lgtm inside
# lifecycle.yml calls `gh pr merge --auto`, which needs contents: write
permissions:
  issues: write
  pull-requests: write
  contents: write   # required even though most jobs only need read
```

Silent failure mode: the callee job runs without errors, but any operation that needs write
(merge, push, tag) returns a silent 403.

### PR branch rebase with conflicting intermediate commits

When a PR branch contains an intermediate "stepping stone" commit that conflicts with main,
do not attempt a full rebase of the branch. Instead:

1. Create a new branch off `origin/main`
2. `git cherry-pick <final-commit-SHA>` - skip the intermediate commit entirely
3. Resolve any conflict in the final commit (usually trivial)
4. Force-push to the PR branch

This avoids pulling obsolete intermediate state into main and produces a clean single commit.
