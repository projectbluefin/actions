---
name: reusable-workflow
description: Reference for reusable-build.yml and reusable-release.yml in projectbluefin/actions. Covers cross-repo action ref resolution, digest output shape, JSON array inputs, SBOM artifact naming, release modes (image stable and semver), and permissions hardening. Load when authoring or debugging these reusable workflows.
metadata:
  type: reference
---

# Reusable Workflows

The repo provides two reusable workflows:

| Workflow | Purpose |
|---|---|
| `.github/workflows/reusable-build.yml` | Full Fedora bootc image build pipeline (Path 1) |
| `.github/workflows/reusable-release.yml` | Image stable-release orchestration and Conventional Commits GitHub Release creation |

**Permissions hardening:** default reusable workflows to `permissions: {}` at the workflow level, then grant the minimum required scopes per job. Do not rely on workflow-level `packages: write`/`contents: write` unless every job in the file truly needs that access.

## Contents
- [reusable-build.yml — calling from a consuming repo](#reusable-buildyml--calling-from-a-consuming-repo)
- [How action refs work inside the reusable workflow](#how-action-refs-work-inside-the-reusable-workflow)
- [Tag generation and manifest scope](#tag-generation-and-manifest-scope)
- [Digest output shape](#digest-output-shape-multi-arch-safe)
- [JSON array inputs](#json-array-inputs)
- [SBOM artifact shape](#sbom-artifact-shape)
- [reusable-release.yml](#reusable-releaseyml--calling-from-a-consuming-repo)

---

## `reusable-build.yml` — calling from a consuming repo

```yaml
jobs:
  build:
    uses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1
    secrets: inherit
    with:
      brand_name: bluefin
      stream_name: stable
      image_flavors: '["main", "nvidia-open"]'
      architecture: '["x86_64"]'
```

---

## How action refs work inside the reusable workflow

When a consuming repo calls the workflow:
- `github.repository` = the **caller's** repo (e.g. `projectbluefin/bluefin`)
- `actions/checkout` checks out the **caller's** code into `GITHUB_WORKSPACE`
- `just` commands run against the **caller's** Justfile — this is intentional

> **Critical: cross-repo action refs**
> When the reusable workflow is called cross-repo (e.g. from `projectbluefin/bluefin`), `uses: ./bootc-build/<name>` resolves to the **caller's** checked-out workspace — not the actions repo. This causes `Can't find action.yml` errors.
> Always use full SHA-pinned refs inside the reusable workflow:
>
> ```yaml
> uses: projectbluefin/actions/bootc-build/setup-runner@<SHA>
> ```
>
> Never use `./bootc-build/...` in `.github/workflows/reusable-build.yml`.

Inside the reusable workflow, cross-repo composite action calls must use fully qualified `projectbluefin/actions/bootc-build/<name>@<SHA>` refs, while the Justfile-driven build steps continue to run caller-specific logic from the checked-out consumer repo.

**Keep self-refs in lockstep:** when bumping reusable workflow self-references, update **all** `projectbluefin/actions/bootc-build/*@<SHA>` entries in that workflow family to the same tested commit. Mixing self-ref SHAs means one pipeline can execute different generations of this repo's actions in a single run.

**Retry GitHub API polling in reusable workflows:** wrap `gh api` polling for other workflow runs (for example, `post-testing-e2e` release-gate lookups) with `projectbluefin/actions/actions/retry@<SHA>` and write the API response to `${{ runner.temp }}`. The retry action executes `with.command` via `eval`, so keep the command free of unescaped double quotes — prefer single-quoted headers plus escaped `?` / `&` separators when redirecting API output to a file. If the retried helper lives in another reusable workflow such as `reusable-release-gate.yml`, bump every caller's pinned `projectbluefin/actions/.github/workflows/...@<SHA>` ref in the same PR so consumers execute the retried helper instead of the previous commit.

Pin GitHub-hosted Linux jobs to explicit runner labels (`ubuntu-24.04` / `ubuntu-24.04-arm`) instead of `ubuntu-latest`, and set `timeout-minutes` on every lightweight helper job (`preflight`, `check`, `collect-digests`, release/validation/report jobs). The build matrix itself gets the longer explicit timeout because it can otherwise hold a runner indefinitely when podman or registry operations hang.

---

## Tag generation and manifest scope

`reusable-build.yml` intentionally keeps tag generation in the caller repo by running `just generate-build-tags` instead of `bootc-build/generate-tags`. That is part of the Path 1 Justfile contract, alongside `image_name`, `generate-default-tag`, `build-ghcr`, and `tag-images`.

`bootc-build/generate-tags` exists for Path 2 / à la carte pipelines that want the shared default tag policy without adopting the full reusable workflow contract.

`bootc-build/create-manifest` is also a Path 2 building block today. The reusable workflow builds and pushes per-architecture images and emits digests, but it does **not** assemble or push a multi-arch manifest index; callers that need a manifest job should add an explicit follow-on `create-manifest` step in their own workflow.

---

## Digest output shape (multi-arch safe)

The `digests` output is a nested JSON map: `{ "image-name": { "platform": "digest" } }`. Platform keys use OCI names (`amd64`, `arm64`), mapped from runner architecture names (`x86_64`, `aarch64`) during artifact writing. Single-arch builds produce one platform key per image; multi-arch builds produce one per architecture.

This shape is directly compatible with `create-manifest`'s `digests-json` input — callers can iterate the outer map and pass each inner object to `create-manifest` without reshaping.

The digest artifact files use pipe-delimited format (`image_name|oci_platform|digest`) so that the `collect-digests` job can build the nested structure without key collisions across architectures.

---

## JSON array inputs

Any input consumed via `fromJson()` must be valid JSON. That means string items inside the array must use **double quotes**.

Always use **single outer quotes** with **double-quoted inner strings**:

```yaml
# ✅ correct
image_flavors: '["main", "nvidia-open"]'
architecture: '["x86_64", "aarch64"]'
install-tools: '["just", "cosign", "oras", "syft"]'
```

Wrong:

```yaml
# ❌ wrong — invalid JSON, fromJson() will fail
architecture: "['x86_64']"
```

The reusable workflow's `architecture` input is the concrete pattern to follow because the matrix parses it with `fromJson(inputs.architecture)`. Use `architecture: '["x86_64"]'` or `architecture: '["x86_64", "aarch64"]'`, never single-quoted strings inside the JSON array.

---

## SBOM artifact shape

The workflow stages SBOMs as `IMAGE_NAME.sbom.json` (flat rename from `sbom_out/IMAGE_NAME/sbom.json`) before upload. The `generate-release.yml` workflow expects this `*.sbom.json` glob shape.

SBOM generation and upload should run for every non-PR build, including the `testing` stream. Weekly promotions retag testing digests directly to production tags, so skipping SBOM on testing leaves promoted images without signed SBOM referrers.

---

## Promotion gate retries and stale-e2e recovery

`reusable-release-gate.yml` treats the e2e lookup as a two-layer retry boundary:

- short GitHub API hiccups (`502/503/504`, rate limits, timeouts) retry up to 3 times with a 30 second backoff
- stale or still-pending e2e coverage re-checks the gate up to 4 times total with 10m / 20m / 30m waits between checks

When the latest relevant `post-testing-e2e` / `post-merge-e2e` run is older than the stale threshold (default 120 minutes), the gate attempts a `workflow_dispatch` re-run before waiting again. If the gate still cannot clear after the final check, it auto-files or updates a `priority/p1` issue titled `promotion blocked for >2h on <branch>` in the caller repo and keeps the workflow failed.

---

## `reusable-release.yml` — calling from a consuming repo

### Image stable-release mode (artifact path)

Use this when your build workflow uploads a `*.sbom.json` artifact via `reusable-build.yml`:

```yaml
jobs:
  release:
    uses: projectbluefin/actions/.github/workflows/reusable-release.yml@v1
    secrets:
      github_token: ${{ secrets.GITHUB_TOKEN }}
    with:
      stream_name: stable
      build_workflow: build-image-stable.yml
      build_branch: stable
      image: ghcr.io/projectbluefin/bluefin
      project_name: Bluefin
      cert_identity_regexp: ^https://github\.com/projectbluefin/(bluefin|actions)/\.github/workflows/
      notable_packages: >-
        [
          {"sbom_name": "kernel",         "label": "Kernel"},
          {"sbom_name": "gnome-shell",    "label": "GNOME Shell"},
          {"sbom_name": "mesa-filesystem","label": "Mesa"},
          {"sbom_name": "flatpak",        "label": "Flatpak"},
          {"sbom_name": "systemd",        "label": "systemd"}
        ]
```

This mode finds the latest successful build run for the requested stream, downloads the uploaded SBOM artifact, resolves the current image digest, and calls `bootc-build/create-release` to publish the GitHub Release. The reusable workflow owns the `production` environment gate and grants only `contents: write` plus `actions: read` to the image release job.

Image release notes also embed the latest testsuite desktop screenshot at:
`https://projectbluefin.github.io/testsuite/screenshots/<slug>-smoke-latest.png`
where `<slug>` is the image ref with the registry/org prefix removed and `:` replaced by `-`
(for example `ghcr.io/projectbluefin/bluefin:stable` → `bluefin-stable`).

### Image inline-SBOM mode (promote-from-testing path)

Use `generate_sbom_inline: true` when promotion retags a testing image directly (no intermediate build run with a SBOM artifact to download). The workflow pulls the promoted image via `skopeo copy` to a local OCI archive, then scans it with Syft using all catalogers. The job fails hard if Syft fails — no silent stub.

```yaml
    with:
      stream_name: stable
      image: ghcr.io/projectbluefin/bluefin
      generate_sbom_inline: true
      checkout_ref: main
      # ... other inputs
```

**Do NOT use `generate_sbom_inline: true` for BST-built images** (e.g. dakota). BST images have no RPM/dpkg database — Syft returns 0 or 1 packages. Use the artifact path instead and upload the BST-native SBOM (from `just sbom` / `buildstream-sbom`) with a static artifact name.

### `notable_packages` — SPDX name reference

`sbom_name` must match the exact `name` field in the SPDX packages array. Values differ by image type:

| Package | Fedora/CentOS RPM (`sbom_name`) | BST/GNOME OS (`sbom_name`) |
|---|---|---|
| Kernel | `kernel` | `linux` |
| GNOME Shell | `gnome-shell` | `gnome-shell` |
| Mesa | `mesa-filesystem` | `mesa` |
| Flatpak | `flatpak` | `flatpak` |
| systemd | `systemd` | `systemd` |
| bootc | `bootc` | `bootc` |

Unmatched entries are silently skipped — no error. Verify against a real SBOM if the Key Components table is empty.

### Variants table (multi-image promotions)

`reusable-release.yml` generates release notes for a single primary image. For repos that promote multiple variants (e.g. `bluefin` + `bluefin-nvidia`), add a `post-release-variants` job that prepends a digest table after `release-notes` completes. See `projectbluefin/bluefin:.github/workflows/execute-release.yml` for the reference implementation.

## `reusable-execute-release.yml` — stable promotion gate

Promotes one or more OCI variants (e.g. `:testing` → `:stable`) for bootc image repos. The workflow resolves the source digest once, optionally runs testsuite e2e against that exact digest, then re-verifies cosign and promotes the same digest to the target tag. The digest is never re-resolved after the gate, eliminating TOCTOU drift between test and promotion.

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `registry` | no | `ghcr.io/projectbluefin` | Registry prefix for image refs |
| `variants` | **yes** | — | JSON array of `{image, source_tag, target_tag}` objects |
| `cosign_identity_regexp` | **yes** | — | Cosign certificate identity regexp for re-verification |
| `fast_forward_branch` | no | `''` | Branch to fast-forward after promotion (e.g. `main`) |
| `fast_forward_sha` | no | `github.sha` | SHA to fast-forward the branch to |
| `tag_name` | no | `''` | Release tag for Discord notification |
| `run_release_gate` | no | `true` | Run testsuite e2e against the candidate digest before promotion |
| `gate_suites` | no | `smoke,common` | Comma-separated suites for the release gate |

### Caller example

```yaml
jobs:
  execute:
    uses: projectbluefin/actions/.github/workflows/reusable-execute-release.yml@v1
    secrets: inherit
    permissions:
      actions: read
      contents: write
      issues: write
      packages: write
      pull-requests: write
    with:
      registry: ghcr.io/projectbluefin
      variants: >-
        [
          {"image":"bluefin","source_tag":"testing","target_tag":"stable"}
        ]
      cosign_identity_regexp: ^https://github\.com/projectbluefin/(bluefin|actions)/\.github/workflows/
      gate_suites: smoke,common
```

### Gate behavior

- The gate runs one matrix job per variant, so multi-variant promotions test each image independently.
- The e2e job calls `projectbluefin/testsuite/.github/workflows/e2e.yml` pinned to the current `v1` SHA.
- The image ref passed to testsuite uses the digest resolved in the `resolve` job (`ghcr.io/projectbluefin/<image>@sha256:…`), not the source tag.
- Set `run_release_gate: false` only as an emergency escape hatch; changing the default affects every consumer of this reusable workflow.

### Permissions

The caller must grant `packages: write` so the nested testsuite workflow can push desktop-screenshot OCI artifacts. The promotion job itself needs `contents: write`, `issues: write`, `packages: write`, and `pull-requests: write` for the release mechanics.

---

### Legacy semver mode

```yaml
jobs:
  release:
    uses: projectbluefin/actions/.github/workflows/reusable-release.yml@v1
    secrets:
      github_token: ${{ secrets.GITHUB_TOKEN }}
    with:
      tag: ${{ github.ref_name }}   # e.g. v1.2.3
      # draft: false                # optional
      # prerelease: false           # optional
      # cliff-config: cliff.toml    # optional; defaults to repo root
```

The legacy semver mode checks out with `fetch-depth: 0` (required by git-cliff), runs `generate-release-notes`, and creates a GitHub Release with the generated body.

**`cliff.toml` requirement:** a `cliff.toml` must exist in the caller's repo root (or override via `cliff-config` input). A factory-wide config is available at the root of this repo and can be copied verbatim.
