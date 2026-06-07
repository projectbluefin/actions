---
name: consumer-guide
description: Onboards a new bootc image repo to use projectbluefin/actions. Covers Path 1 (full reusable-build.yml workflow with Justfile contract) and Path 2 (à la carte composite actions), SHA pinning strategy, known constraints, and pre-live checklist. For upgrade/migration test gates and live consumer examples, see consumer-guide/upgrade-and-migration.md.
metadata:
  type: reference
---

# Consumer Guide — Using These Actions in Your Own bootc Image

How to wire `projectbluefin/actions` into a custom Fedora-based bootc image repo.

## Contents
- [Two paths](#two-paths)
- [Path 1 — Full reusable workflow](#path-1--full-reusable-workflow)
- [Path 2 — Composite actions à la carte](#path-2--composite-actions-à-la-carte)
- [Versioning and SHA pinning](#versioning-and-sha-pinning)
- [Known constraints](#known-constraints)
- [Checklist before going live](#checklist-before-going-live)
- [Getting help](#getting-help)

**Sub-file (load as needed):**
- [`consumer-guide/upgrade-and-migration.md`](consumer-guide/upgrade-and-migration.md) — upgrade test gate, migration test, dakota notes, live consumer examples

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

> **Easiest path:** fork the [bluefin Justfile](https://github.com/projectbluefin/bluefin/blob/main/Justfile) as a starting point and adapt it for your image name and base.

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

### Output

```yaml
outputs:
  digests:   # Nested JSON: { "my-image-main": { "amd64": "sha256:abc..." } }
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
| `validate-pr` | `bootc-build/validate-pr@v1` | Run just check, shellcheck, hadolint, pre-commit |
| `generate-tags` | `bootc-build/generate-tags@v1` | Generate shared Bluefin/Fedora OCI alias tags |
| `push-image` | `bootc-build/push-image@v1` | Push with retry, digest capture, skopeo alias tags |
| `create-manifest` | `bootc-build/create-manifest@v1` | Multi-arch OCI manifest index assembly |
| `sign-and-publish` | `bootc-build/sign-and-publish@v1` | Cosign (keyless or key) + Syft SBOM + attestation |
| `rechunk` | `bootc-build/rechunk@v1` | rpm-ostree `zstd:chunked` rechunking with delta support |
| `chunka` | `bootc-build/chunka@v1` | OCI-native chunkah rechunking (no rpm-ostree needed) |
| `ghcr-cleanup` | `bootc-build/ghcr-cleanup@v1` | Prune old/untagged GHCR images |

`generate-tags` is for **Path 2** and other custom pipelines. **Path 1** does not use it; tag generation stays in the caller's Justfile.

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

      - uses: projectbluefin/actions/bootc-build/setup-runner@v1
        with:
          storage-backend: btrfs
          install-tools: '["cosign", "oras", "syft"]'

      - uses: projectbluefin/actions/bootc-build/dnf-cache@v1
        id: dnf-cache-restore
        with:
          action: restore
          cache-name: my-image-42
          image-flavor: ${{ matrix.image_flavor }}

      - name: Build image
        run: |
          sudo podman build \
            --tag my-image:latest \
            --label "org.opencontainers.image.version=42.$(date +%Y%m%d)" \
            .

      - uses: projectbluefin/actions/bootc-build/dnf-cache@v1
        with:
          action: save
          cache-name: my-image-42
          image-flavor: ${{ matrix.image_flavor }}

      - if: github.event_name != 'pull_request'
        uses: projectbluefin/actions/bootc-build/push-image@v1
        id: push
        with:
          image-name: my-image
          tags: "latest"
          github-token: ${{ secrets.GITHUB_TOKEN }}

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
        runner: ubuntu-24.04-arm

jobs:
  build:
    runs-on: ${{ matrix.runner }}
    outputs:
      digest: ${{ steps.push.outputs.digest }}
    # ... build and push per-arch image ...

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

Pin to `@v1` for stability. To test against a feature branch before it merges:

```yaml
uses: projectbluefin/actions/.github/workflows/reusable-build.yml@abc1234
```

Move back to `@v1` after the branch merges. Renovate manages SHA bumps automatically.

---

## Known constraints

| Constraint | Detail |
|---|---|
| Fedora only (reusable workflow) | The rechunk step uses rpm-ostree and assumes Fedora OSTree base. CentOS/Alpine users should use composite actions à la carte with `chunka` |
| Justfile contract is strict | All 7 required recipes must exist with the exact expected signatures |
| `aarch64` requires ARM runner | Self-hosted or GitHub-hosted `ubuntu-24.04-arm`; not included in the default free-tier |
| Registry hardcoded to GHCR | The `IMAGE_REGISTRY` env var is `ghcr.io/${{ github.repository_owner }}`; override only via composite actions |
| CentOS Stream requires explicit compression | Set `force-compression: true` on both `chunka` and `push-image`. Fedora consumers must leave both at the default `false` |
| SBOM on all non-PR streams | `testing` stream builds include SBOM — weekly promotions retag testing digests to stable, so SBOM coverage is required end-to-end |
| Multi-arch matrix stays in the consumer workflow | Do not move matrix orchestration into shared actions. Shared actions are per-arch steps; the matrix stays in the consumer workflow |

---

## Checklist before going live

- [ ] Justfile has all 7 required recipes with correct signatures
- [ ] `permissions: id-token: write` in the calling job (required for keyless cosign)
- [ ] `secrets: inherit` (or explicit `GITHUB_TOKEN`) passed to the reusable workflow
- [ ] GHCR package visibility set to public, or `GITHUB_TOKEN` has write access
- [ ] `stream_name` is one of `stable`, `latest`, `beta`, `testing`
- [ ] `image_flavors` and `architecture` use double-quoted strings inside the JSON array: `'["main"]'` not `"['main']"`
- [ ] Tested with `stream_name: testing` first (faster feedback loop)
- [ ] Opened a draft PR in your repo to validate the integration before merging
- [ ] Added a `skill-drift.yml` wrapper calling `skill-drift-check.yml@v1` — see `docs/skills/factory-operations.md` → "Skill-Drift PR Check"
- [ ] Production promotion workflow gated behind `environment: production` with 2 required reviewers

---

## Getting help

- File issues at [projectbluefin/actions](https://github.com/projectbluefin/actions/issues)
- Working examples: [projectbluefin/bluefin](https://github.com/projectbluefin/bluefin) (Path 1) and [projectbluefin/bluefin-lts](https://github.com/projectbluefin/bluefin-lts) (Path 2 à la carte)
