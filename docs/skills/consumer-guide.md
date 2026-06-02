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
9. Generates an SBOM (Syft → ORAS attach), skipped on `stream_name: testing`
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
        with:
          action: restore
          cache-name: my-image-42         # include Fedora/distro version in name

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
| CentOS Stream requires explicit compression | If your consumer is CentOS Stream 10 or another non-Fedora OS, set `force-compression: true` on both `chunka` and `push-image` actions due to zstd layer migration requirements. Fedora consumers can leave this at the default `false`. |

---

## Known constraints

| Constraint | Detail |
|---|---|
| Fedora only (reusable workflow) | The rechunk step uses rpm-ostree and assumes Fedora OSTree base. CentOS/Alpine users should use composite actions à la carte with `chunka` instead |
| Justfile contract is strict | All 7 required recipes must exist with the exact expected signatures |
| `aarch64` requires ARM runner | Self-hosted or GitHub-hosted `ubuntu-24.04-arm`; not included in the default free-tier |
| Registry hardcoded to GHCR | The `IMAGE_REGISTRY` env var is `ghcr.io/${{ github.repository_owner }}`; override only via composite actions |
| SBOM skipped on `testing` stream | By design — testing stream trades provenance for speed. Promoted images inherit the gap until signing is added pre-promotion |

---

## Checklist before going live

- [ ] Justfile has all 7 required recipes with correct signatures
- [ ] `permissions: id-token: write` in the calling job (required for keyless cosign)
- [ ] `secrets: inherit` (or explicit `GITHUB_TOKEN`) passed to the reusable workflow
- [ ] GHCR package visibility set to public, or `GITHUB_TOKEN` has write access
- [ ] `stream_name` is one of `stable`, `latest`, `beta`, `testing`
- [ ] `image_flavors` and `architecture` use double-quoted strings inside the JSON array: `'["main"]'` not `"['main']"`
- [ ] Tested with `stream_name: testing` first (skips SBOM/signing/rechunk — faster feedback loop)
- [ ] Opened a draft PR in your repo to validate the integration before merging
- [ ] Added a `skill-drift.yml` wrapper calling `skill-drift-check.yml@v1` — see `docs/skills/factory-operations.md` → "Skill-Drift PR Check" for the 16-line template and path configs per repo type
- [ ] Production promotion workflow gated behind `environment: production` with 2 required reviewers configured in GitHub Settings → Environments

---

## Getting help

- File issues at [projectbluefin/actions](https://github.com/projectbluefin/actions/issues)
- Working examples: [projectbluefin/bluefin](https://github.com/projectbluefin/bluefin) and [ublue-os/aurora](https://github.com/ublue-os/aurora)
