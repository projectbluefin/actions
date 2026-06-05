# Consumer Guide — Using These Actions in Your Own bootc Image

How to wire `projectbluefin/actions` into a custom Fedora-based bootc image repo.

---

## Two paths

| Path | When to use |
|---|---|
| **Full reusable workflow** | Your image follows the bluefin/aurora build model (Fedora base, Justfile-driven, GHCR push) |
| **Composite actions à la carte** | You have a custom pipeline, non-Fedora base, or multi-arch needs |

---

## Path 1 — Full reusable workflow

### Prerequisites

Your repo must satisfy a **Justfile contract**: the reusable workflow calls specific recipes from your checked-out repo. All recipe signatures must match exactly.

| Recipe | Signature | What it must do |
|---|---|---|
| `check` | `just check` | Validate repo health (lint, format); exit non-zero on failure |
| `image_name` | `just image_name <base> <stream> <flavor>` | Print the image name to stdout (e.g. `my-image`) |
| `generate-default-tag` | `just generate-default-tag <stream> <ghcr> [kernel_pin]` | Print the primary OCI tag (e.g. `latest`) |
| `generate-build-tags` | `just generate-build-tags <image> <stream> <flavor> [kernel_pin] <ghcr> [version] <event> <number>` | Print newline-separated alias tags |
| `setup-cache` | `just setup-cache <base> <stream> <ghcr> <event>` | Print the cache key fragment; optionally configure OCI layer cache |
| `build-ghcr` | `just build-ghcr <image> <stream> <flavor> [kernel_pin]` | Build the image into local podman storage as `<image>:<default-tag>` |
| `tag-images` | `just tag-images <image_name> <default_tag> <tags>` | Apply alias tags to the locally built image |

> **Easiest path:** fork the [bluefin Justfile](https://github.com/projectbluefin/bluefin/blob/main/Justfile) as a starting point and adapt it for your image name and base. The recipe signatures are stable across bluefin, aurora, and bazzite — change the `brand_name` input and the underlying `Containerfile`, not the recipe contracts.

### Minimal caller workflow

```yaml
# .github/workflows/build.yml
name: Build My Image

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  build:
    uses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1
    secrets: inherit
    with:
      brand_name: my-image        # must match your image_name recipe output
      stream_name: latest         # stable | latest | beta | testing
      image_flavors: '["main"]'   # JSON array; each entry is passed as <flavor> to Justfile
      architecture: '["x86_64"]'  # '["x86_64"]' or '["x86_64", "aarch64"]'
```

### Full inputs reference

| Input | Required | Default | Description |
|---|---|---|---|
| `brand_name` | no | `bluefin` | Passed as `<base>` to all Justfile recipes |
| `stream_name` | **yes** | — | `stable`, `latest`, `beta`, or `testing` |
| `image_flavors` | no | `'["main", "nvidia-open"]'` | JSON array of flavor strings |
| `architecture` | no | `'["x86_64"]'` | JSON array; `aarch64` requires self-hosted ARM runner |
| `kernel_pin` | no | `""` | Full kernel version string; passed through to build and tag recipes |
| `pr_number` | no | `""` | Set by `e2e-dispatch.yml` — scopes tags to the PR number |

### What the workflow does for you

**On every push (non-PR):**
1. Runs `just check` (preflight)
2. Restores DNF/buildah cache
3. Logs into GHCR
4. Runs `just build-ghcr` with the matrix parameters
5. Rechunks the image (rpm-ostree `zstd:chunked`)
6. Generates alias tags via `just generate-build-tags`
7. Pushes to `ghcr.io/<your-org>/<image_name>` with all alias tags
8. Signs with cosign (keyless OIDC)
9. Generates an SBOM (Syft → ORAS attach) on all non-PR streams including `testing`
10. Pushes GitHub Attestation
11. Saves DNF cache

**On PRs:**
1-4 same (but no GHCR login/push)
5. Exports the image as a `.oci` artifact for local testing
6. Prints `bootc switch` instructions for the PR image

### Output

```yaml
outputs:
  digests:   # JSON map: { "my-image-main": "sha256:abc..." }
```

Consume downstream in a signing or release job:

```yaml
jobs:
  build:
    uses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1
    secrets: inherit
    with:
      brand_name: my-image
      stream_name: stable
      image_flavors: '["main"]'
      architecture: '["x86_64"]'

  release:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - run: echo "Digests = ${{ needs.build.outputs.digests }}"
```

---

## Path 2 — Composite actions à la carte

Use individual actions when you need more control: different base distro (CentOS, Alpine), multi-arch manifest, non-Justfile build system, or custom signing.

### Action catalog

| Action | `uses:` path | Purpose |
|---|---|---|
| `setup-runner` | `bootc-build/setup-runner@v1` | Update podman, set up BTRFS storage, install tools |
| `dnf-cache` | `bootc-build/dnf-cache@v1` | Restore/save buildah layer cache |
| `preflight` | `bootc-build/preflight@v1` | Validate registry auth, normalize image refs |
| `detect-changes` | `bootc-build/detect-changes@v1` | Detect changed paths, compute image-flavor build matrix |
| `validate-pr` | `bootc-build/validate-pr@v1` | Run just check, shellcheck, hadolint, pre-commit. Optional: `system-files-shellcheck-glob` (shellcheck extra glob), `enable-desktop-file-validate` (validate `.desktop` files), `check-submodule-drift` (fail if submodule is dirty) |
| `generate-tags` | `bootc-build/generate-tags@v1` | Generate shared Bluefin/Fedora OCI alias tags from version + event context |
| `push-image` | `bootc-build/push-image@v1` | Push with retry, digest capture, skopeo alias tags |
| `create-manifest` | `bootc-build/create-manifest@v1` | Multi-arch OCI manifest index assembly |
| `sign-and-publish` | `bootc-build/sign-and-publish@v1` | Cosign (keyless or key) + Syft SBOM + attestation |
| `rechunk` | `bootc-build/rechunk@v1` | rpm-ostree `zstd:chunked` rechunking with delta support |
| `chunka` | `bootc-build/chunka@v1` | OCI-native chunkah rechunking (no rpm-ostree needed) |
| `ghcr-cleanup` | `bootc-build/ghcr-cleanup@v1` | Prune old/untagged GHCR images |

`generate-tags` is for **Path 2** and other custom pipelines that want the shared Bluefin tag policy without reimplementing it. **Path 1** does not use this action; the reusable workflow keeps tag generation in the caller's Justfile contract via `just generate-build-tags`. Prefer `generate-tags` when you are assembling your own workflow from individual actions, and prefer the Justfile recipe when you are adopting the full reusable workflow and want tag policy owned by the consumer repo.

### Minimal custom pipeline

```yaml
jobs:
  build:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      packages: write
      id-token: write    # required for keyless cosign signing

    steps:
      - uses: actions/checkout@v4

      # 1. Prepare runner
      - uses: projectbluefin/actions/bootc-build/setup-runner@v1
        with:
          storage-backend: btrfs          # or 'remove-software'
          install-tools: '["cosign", "oras", "syft"]'

      # 2. Restore cache
      - uses: projectbluefin/actions/bootc-build/dnf-cache@v1
        id: dnf-cache-restore
        with:
          action: restore
          cache-name: my-image-42         # include Fedora/distro version in name
          image-flavor: ${{ matrix.image_flavor }}  # partition cache per flavor (main, nvidia-open, etc.)

      # 3. Build (your build system here)
      - name: Build image
        run: |
          sudo podman build \
            --tag my-image:latest \
            --label "org.opencontainers.image.version=42.$(date +%Y%m%d)" \
            .

      # 4. Save cache
      - uses: projectbluefin/actions/bootc-build/dnf-cache@v1
        with:
          action: save
          cache-name: my-image-42
          image-flavor: ${{ matrix.image_flavor }}

      # 5. Push (non-PR only)
      - if: github.event_name != 'pull_request'
        uses: projectbluefin/actions/bootc-build/push-image@v1
        id: push
        with:
          image-name: my-image
          tags: "latest"
          github-token: ${{ secrets.GITHUB_TOKEN }}

      # 6. Sign + SBOM (non-PR only)
      - if: github.event_name != 'pull_request'
        uses: projectbluefin/actions/bootc-build/sign-and-publish@v1
        with:
          image-ref: ghcr.io/${{ github.repository_owner }}/my-image
          digest: ${{ steps.push.outputs.digest }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
          signing-mode: keyless
          generate-sbom: "true"
```

### Multi-arch pipeline (with manifest)

```yaml
strategy:
  matrix:
    arch: [x86_64, aarch64]
    include:
      - arch: x86_64
        runner: ubuntu-24.04
      - arch: aarch64
        runner: ubuntu-24.04-arm  # or self-hosted ARM runner

jobs:
  build:
    runs-on: ${{ matrix.runner }}
    # ... build steps, push per-arch image ...
    outputs:
      digest: ${{ steps.push.outputs.digest }}

  manifest:
    needs: build
    runs-on: ubuntu-24.04
    steps:
      - uses: projectbluefin/actions/bootc-build/create-manifest@v1
        with:
          image-name: my-image
          tags: "latest"
          digests-json: >-
            {
              "amd64": "${{ needs.build.outputs.digest-amd64 }}",
              "arm64": "${{ needs.build.outputs.digest-arm64 }}"
            }
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

> **Note:** `create-manifest` does **not** install its dependencies. Ensure `podman` and `jq` are available on the runner.

---

## Versioning and SHA pinning

Pin to `@v1` for stability. If you need to test against a feature branch before it merges to `main`:

```yaml
# Pin to a specific commit on a feature branch
uses: projectbluefin/actions/.github/workflows/reusable-build.yml@abc1234
```

Move back to `@v1` after the branch merges. Renovate manages SHA bumps automatically via the `github-actions` manager.

---

## Image registry

The reusable workflow always pushes to `ghcr.io/<github.repository_owner>/<image_name>`. There is currently no input to override the registry. For other registries, use `push-image` directly.

---

## Multi-repo consumers: known pitfalls

When your repo has multiple git remotes (e.g., forked from upstream), take care:

| Pitfall | How to avoid |
|---|---|
| Pushing to the wrong remote | Run `git remote -v` before pushing. If your feature branch is tracking `origin`, but you meant to push to `projectbluefin`, specify `git push projectbluefin <branch>` explicitly. In high-activity repos, always double-check the remote name. |
| Feature branches go stale quickly | High-velocity repos like `bluefin-lts` (1400+ merged PRs, constant digest bumps via Renovate) can make a feature branch outdated within hours. Rebase onto the target remote's `main` before opening or re-opening a PR: `git rebase projectbluefin/main` |
| Multi-arch matrix stays in the consumer workflow | Do not move matrix orchestration (`generate_matrix`, per-arch build matrix, conditional arm64 logic) into shared actions. Shared actions are per-arch steps; the matrix stays in the consumer workflow. This keeps the action catalog focused and lets each consumer tune its own build strategy. |
| CentOS Stream requires explicit compression | If your consumer is CentOS Stream 10 or another non-Fedora OS, set `force-compression: true` on both `chunka` and `push-image` actions. In `chunka` this passes `--compression-format zstd:chunked --force-compression` to `buildah build`. In `push-image` it adds `--force-compression` to `podman push`. Fedora consumers must leave both at the default `false` — Fedora images are already zstd:chunked and forcing recompression strips `ostree.components` layer annotations. |

---

## Known constraints

| Constraint | Detail |
|---|---|
| Fedora only (reusable workflow) | The rechunk step uses rpm-ostree and assumes Fedora OSTree base. CentOS/Alpine users should use composite actions à la carte with `chunka` instead |
| Justfile contract is strict | All 7 required recipes must exist with the exact expected signatures |
| `aarch64` requires ARM runner | Self-hosted or GitHub-hosted `ubuntu-24.04-arm`; not included in the default free-tier |
| Registry hardcoded to GHCR | The `IMAGE_REGISTRY` env var is `ghcr.io/${{ github.repository_owner }}`; override only via composite actions |
| SBOM on all non-PR streams | `testing` stream builds now include SBOM — weekly promotions retag testing digests to stable, so SBOM coverage is required end-to-end |

---

## Checklist before going live

- [ ] Justfile has all 7 required recipes with correct signatures
- [ ] `permissions: id-token: write` in the calling job (required for keyless cosign)
- [ ] `secrets: inherit` (or explicit `GITHUB_TOKEN`) passed to the reusable workflow
- [ ] GHCR package visibility set to public, or `GITHUB_TOKEN` has write access
- [ ] `stream_name` is one of `stable`, `latest`, `beta`, `testing`
- [ ] `image_flavors` and `architecture` use double-quoted strings inside the JSON array: `'["main"]'` not `"['main']"`
- [ ] Tested with `stream_name: testing` first (faster feedback loop — skips rechunk but still runs signing and SBOM)
- [ ] Opened a draft PR in your repo to validate the integration before merging
- [ ] Added a `skill-drift.yml` wrapper calling `skill-drift-check.yml@v1` — see `docs/skills/factory-operations.md` → "Skill-Drift PR Check" for the 16-line template and path configs per repo type
- [ ] Production promotion workflow gated behind `environment: production` with 2 required reviewers configured in GitHub Settings → Environments

---

## Upgrade test

A post-build gate: after your image is built and pushed, call this workflow with
the new image ref. It boots it in QEMU via `projectbluefin/testsuite` and runs the
`lifecycle` suite — upgrade, reboot, rollback, `/etc` persistence, and idempotency.
Only if the gate passes should the image be promoted or tagged stable.

### Minimal wiring — build → gate → promote

```yaml
jobs:
  build:
    # ... your build steps ...
    outputs:
      image: ${{ steps.push.outputs.registry-path }}/your-image
      digest: ${{ steps.push.outputs.digest }}

  upgrade-test:
    needs: build
    uses: projectbluefin/actions/.github/workflows/upgrade-test.yml@v1
    permissions:
      contents: read
      packages: write
    with:
      image: ${{ needs.build.outputs.image }}@${{ needs.build.outputs.digest }}

  promote:
    needs: upgrade-test
    if: needs.upgrade-test.outputs.result == 'success'
    # ... move tag, cut release, etc. ...
```

### Hello-world: bluefin

```yaml
# .github/workflows/upgrade-test.yml  (in projectbluefin/bluefin)
name: Upgrade Test

on:
  workflow_dispatch:
    inputs:
      image:
        description: "Full OCI ref of the build to gate on"
        required: false
        default: "ghcr.io/ublue-os/bluefin:stable"
  schedule:
    - cron: "0 6 * * 1"   # weekly on Monday

jobs:
  upgrade-test:
    uses: projectbluefin/actions/.github/workflows/upgrade-test.yml@v1
    permissions:
      contents: read
      packages: write
    with:
      image: ${{ inputs.image || 'ghcr.io/ublue-os/bluefin:stable' }}
```

### Hello-world: bluefin-lts

```yaml
# .github/workflows/upgrade-test.yml  (in projectbluefin/bluefin-lts)
name: Upgrade Test

on:
  workflow_dispatch:
    inputs:
      image:
        description: "Full OCI ref of the build to gate on"
        required: false
        default: "ghcr.io/ublue-os/bluefin-lts:lts"
  schedule:
    - cron: "0 6 * * 1"   # weekly on Monday

jobs:
  upgrade-test:
    uses: projectbluefin/actions/.github/workflows/upgrade-test.yml@v1
    permissions:
      contents: read
      packages: write
    with:
      image: ${{ inputs.image || 'ghcr.io/ublue-os/bluefin-lts:lts' }}
```

### Inputs reference

| Input | Required | Default | Description |
|---|---|---|---|
| `image` | **yes** | — | Full OCI ref of the image to gate on — tag or digest (e.g. `ghcr.io/ublue-os/bluefin:stable` or `…@sha256:abc`) |
| `suites` | no | `lifecycle` | Comma-separated testsuite suites to run |
| `skip_native_apps` | no | `false` | Skip `@native_app` scenarios |
| `screenshot_flatpaks` | no | `""` | Comma-separated Flatpak IDs to launch-and-screenshot |

### Outputs reference

| Output | Description |
|---|---|
| `result` | Job outcome: `success`, `failure`, `cancelled`, or `skipped` — use in `if:` conditions for downstream promote jobs |

### What the `lifecycle` suite tests

| Scenario | Tags |
|---|---|
| `bootc status` reports expected image and is not dirty | `@lifecycle @status` |
| Pin and unpin the current deployment | `@lifecycle @pin` |
| `bootc upgrade` stages a new deployment | `@lifecycle @upgrade` |
| VM boots into upgraded deployment after reboot | `@lifecycle @upgrade @reboot` |
| `bootc rollback` reverts to previous deployment | `@lifecycle @rollback` |
| `/etc` customizations survive upgrade | `@lifecycle @etc_merge` |
| `ostree admin status` shows two deployments | `@lifecycle @ostree` |
| `os-release` version changes tracked after upgrade | `@lifecycle @upgrade @version` |
| `bootc upgrade` is idempotent when already at latest | `@lifecycle @upgrade @idempotent` |
| Auto-update timer is present and not masked | `@lifecycle @autoupdate` |

Source: [`tests/lifecycle/features/bootc.feature`](https://github.com/projectbluefin/testsuite/blob/main/tests/lifecycle/features/bootc.feature)

### Permissions required

```yaml
permissions:
  contents: read
  packages: write   # testsuite pushes desktop screenshots as OCI artifacts
```

---

## Live Path 2 consumer: dakota (BST/BuildStream)

dakota is structurally different from all other consumers — its image is produced by `bst build oci/bluefin.bst` inside a pinned `bst2` container, not `podman build` of a Containerfile. It is a **Path 2 only** consumer, permanently. The full reusable workflow (`reusable-build.yml`) will never apply.

### What applies to dakota

| Action | Status | Notes |
|---|---|---|
| `setup-runner` | **Adopted** | `update-podman: true`, `storage-backend: btrfs`, `install-tools: '["just"]'` |
| `sign-and-publish` | **Adopted** | `generate-sbom: false` — dakota uses BST-native SBOM via `just sbom` |
| `ghcr-cleanup` | **Adopted** | Weekly cron, packages: `dakota,dakota-nvidia` |
| `push-image` | **Ready to adopt** | Replaces inline retry loop in `publish.yml`. Use `compression-format: zstd` (not the default `zstd:chunked`) |
| `create-manifest` | **Ready to adopt** | Replaces inline `podman manifest create/push` in `build.yml`. Currently blocked on aarch64 build being disabled |
| `dnf-cache` | **N/A** | Wrong cache model. BST uses `~/.cache/buildstream` + remote CAS at `cache.projectbluefin.io` |
| `rechunk` | **N/A** | rpm-ostree/Fedora only |
| `chunka` | **Optional** | Only if dakota decides to produce OTA-delta-friendly rechunked layers |

### What must never be touched

- BST-domain composites (`check-bst2-pin`, `generate-bst-ci-config`) remain local to dakota
- BST remote CAS (`cache.projectbluefin.io`) is outside the shared caching model
- `bst2` container SHA is pinned via `check-bst2-pin` — preserve this
- Never attempt to fit dakota into `reusable-build.yml`
- Never replace BST with rpm-ostree/Containerfile

### Pre-condition for push-image wiring

Before replacing dakota's inline push with `push-image@v1`, verify the push mechanism:

```sh
grep -n 'podman push\|skopeo\|podman load' dakota/.github/workflows/publish.yml | head -20
```

**Proceed only if** the push is a plain `podman push` of a locally-loaded image (exported from BST via `just export`, then tagged). The current `publish.yml` satisfies this — it does `sudo podman tag` then `sudo podman push` with a retry loop.

**Do not proceed if** the push uses `skopeo copy` from BST CAS or requires a `bst artifact checkout` + `podman load` first. In that case, file a child issue describing the adapter needed.

### Dakota push-image usage

```yaml
- uses: projectbluefin/actions/bootc-build/push-image@v1
  id: push
  with:
    image-name: dakota          # or dakota-nvidia
    tags: "${{ needs.setup.outputs.sha }}"
    compression-format: zstd    # BST exports plain OCI, not zstd:chunked
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

---

## Getting help

- File issues at [projectbluefin/actions](https://github.com/projectbluefin/actions/issues)
- Working examples: [projectbluefin/bluefin](https://github.com/projectbluefin/bluefin) (Path 1) and [projectbluefin/bluefin-lts](https://github.com/projectbluefin/bluefin-lts) (Path 2 à la carte)

---

## Live Path 1 consumer: bluefin (extended validation)

bluefin opts into all three optional `validate-pr` inputs:

```yaml
- uses: projectbluefin/actions/bootc-build/validate-pr@v1
  with:
    shellcheck-glob: "build_files/**/*.sh"
    system-files-shellcheck-glob: "system_files/**/*.sh"
    enable-desktop-file-validate: "true"
    check-submodule-drift: "true"
```

Hook scripts that `source` a runtime-only path (e.g. `/usr/lib/ublue/setup-services/libsetup.sh`) must include `# shellcheck source=/dev/null` on the source line to silence SC1091 in CI.

---

## Live Path 2 consumer: bluefin-lts

bluefin-lts uses CentOS Stream 10 (non-Fedora base) and cannot use the full reusable workflow. It calls composite actions individually. Key overrides:

| Action | Override | Why |
|---|---|---|
| `validate-pr` | `shellcheck-glob: "build_scripts/**/*.sh"` | lts uses `build_scripts/`, not `build_files/` |
| `detect-changes` | `filters:` with `build_scripts/**`, `image-versions.yaml` | default paths are bluefin-specific |
| `chunka` | `force-compression: true` | CentOS base must migrate gzip layers to zstd:chunked — passes `--compression-format zstd:chunked --force-compression` to `buildah build` |

This is the reference implementation for any bootc image repo that diverges from the bluefin path convention.
