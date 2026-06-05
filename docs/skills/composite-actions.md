# Composite Actions — Authoring Skill

Reference for writing and maintaining composite GitHub Actions in this repo.

**Update this file** when you discover a new pattern, workaround, or convention — in the same PR as your change.

---

## Structure

Every action lives at `bootc-build/<name>/action.yml`. No build system, no scripting layer — only YAML + inline shell.

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

All `uses:` references to external actions **must** be pinned to a full commit SHA. Append a comment with the human-readable version tag:

```yaml
uses: sigstore/cosign-installer@7e8b541eb2e61bf99390e1afd4be13a184e9ebc5 # v3.10.1
```

Never use floating tags (`@main`, `@v3`, `@latest`). Renovate runs in **this repo** and auto-merges SHA pin and digest bumps when CI passes — the canonical pins live here and propagate to consumers when a maintainer moves `@v1`.

The version comment must match a **released** version tag (e.g. `v3.10.1`, not just `v3`). If a repo has no releases or tags, use a descriptive comment instead:

```yaml
uses: ublue-os/some-action@abc123def456... # no-release, Merge PR #18 (2026-02)
```

---

## Shell steps

### Error handling

Start every non-trivial shell step with:
```bash
set -euo pipefail
```

Use `set -eux` for steps where verbose trace output aids debugging (e.g., package installs).

### Passing inputs to shell

Pass inputs through the `env:` block — do not expand `${{ inputs.foo }}` inline inside `run:` scripts:

```yaml
# ✅ correct
env:
  IMAGE: ${{ inputs.image }}
  DIGEST: ${{ inputs.digest }}
run: |
  cosign sign -y "${IMAGE}@${DIGEST}"

# ❌ wrong — shell injection risk, harder to trace
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

Word splitting on an env var is safe for globs but is NOT command injection — `;` in a variable is not a command separator.

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

Actions that need registry access or GitHub API calls take an explicit `github-token` input (required). The calling workflow supplies `${{ secrets.GITHUB_TOKEN }}` or a PAT — the action never uses it implicitly.

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

## Action-by-action reference

### `setup-runner`

Sets up a GitHub Actions runner for bootc image building. Two storage backends:

- `btrfs` (default): mounts a BTRFS volume at `/var/lib/containers` via `ublue-os/container-storage-action`
- `remove-software`: frees disk by nuking Android/Haskell/dotnet toolchains

Upgrades podman from Ubuntu **resolute** (25.04) because Ubuntu 24.04 runners ship a version too old to support layer annotations (`ostree.components`) and `zstd:chunked` push.

Installs optional tools (`just`, `cosign`, `oras`, `syft`) via `install-tools` JSON array input.

### `dnf-cache`

Wraps `actions/cache/restore` and `actions/cache/save` for the buildah layer cache at `/var/tmp/buildah-cache-*`.

**Known workaround:** cache save requires recursively `chmod 777` on every matching `/var/tmp/buildah-cache-*` directory before the save step — buildah may create multiple numbered cache directories, not just `-0`; see [actions/cache#1533](https://github.com/actions/cache/issues/1533). This is intentional, not a bug.

**Empty-glob guard (cold build):** the `chmod` loop must use `if [[ -d "$d" ]]; then ... fi` rather than `[[ -d "$d" ]] && cmd`. On a cold build where no `/var/tmp/buildah-cache-*` directory exists yet, bash expands the glob to the literal string, `[[ -d "..." ]]` returns false, and the `&&` chain propagates that as a non-zero exit even under `set -e`. The `if` form treats the false branch as a no-op.

Restore behavior should include two fallback tiers: first a flavor-scoped restore key (`${{ runner.os }}-${{ inputs.architecture }}-buildah-<flavor>-` when `image-flavor` is set, or `${{ runner.os }}-${{ inputs.architecture }}-buildah-<cache-name>-` otherwise) for partial matches within the same flavor/version family, then the broader `${{ runner.os }}-${{ inputs.architecture }}-buildah-` fallback.

Save behavior should be guarded with `always() && !cancelled()` so failed builds still persist downloaded packages for the next retry.

Cache key format: `Linux-<arch>-buildah-[<flavor>-]<cache-name>`. Pass `image-flavor` (e.g., `main`, `nvidia-open`) to partition caches per flavor and prevent cross-flavor pollution. The input is optional — callers that don't pass it fall back to the old format.

**Exposing `cache-hit` to the caller:** the composite exposes a `cache-hit` output (`steps.restore.outputs.cache-hit`). To read it in the calling workflow's telemetry/summary, give the `uses:` step an `id:` (e.g., `id: dnf-cache-restore`) and reference `steps.dnf-cache-restore.outputs.cache-hit`. Without the `id`, the output is silently empty.

### `preflight`

Validates registry auth, normalizes image refs to lowercase, and checks required secrets are non-empty.

Outputs `registry-lowercase` and `image-ref` (if `image-name` was supplied).

### `push-image`

Pushes using a configurable `compression-format` (default `zstd:chunked`) via a **single** `sudo -E podman push` for the default tag. Default behavior must **not** pass `--force-compression`: rechunked Fedora images are already `zstd:chunked`, and forcing recompression strips `ostree.components` layer annotations.

The `compression-format` input controls `--compression-format` on `podman push`. Use the default (`zstd:chunked`) for Fedora/rpm-ostree consumers. Use `zstd` for BST-based consumers like dakota that export plain OCI tarballs without chunked layer annotations.

For chunkah-based images that need to migrate existing registry layers from `gzip` to `zstd:chunked` (for example bluefin-lts), expose a `force-compression` input and conditionally append `--force-compression` inside the push loop via an env-backed shell flag.

Capture the pushed digest with `skopeo inspect --no-tags ... | jq -r '.Digest'` after the push instead of doing a second `podman push --digestfile` upload.

Before the user-space registry login, restore ownership of `/run/user/$(id -u)/containers` if it exists. Earlier `sudo podman login` calls in consuming workflows can leave root-owned auth files there and break the later unprivileged login. Keep this as an opt-out input (`fix-auth-permissions`, default `true`) so callers can disable it when unnecessary.

Alias tags are applied server-side via `skopeo copy` (no re-upload).

Retry logic: outer `while` loop up to `max-attempts` (default 3), with `retry-wait-seconds` (default 15s) between attempts. The inner `podman push` also carries `--retry 5 --retry-delay 30s`.

### `generate-tags`

Generates the shared Fedora/Bluefin-style OCI alias tags from the built image's `org.opencontainers.image.version` label plus GitHub event context. Use this in **Path 2** or other custom pipelines that want the repo's stock tag policy without depending on a consumer Justfile.

The reusable workflow intentionally does **not** call this action. **Path 1** keeps tag generation inside the caller's Justfile contract via `just generate-build-tags`, so consuming repos retain control over tag policy and can evolve it without changing shared workflow wiring.

### `create-manifest`

Assembles and pushes a multi-arch OCI manifest index from a JSON map of `platform -> digest` values (for example `{"amd64":"sha256:...","arm64":"sha256:..."}`). The local manifest name should match the lowercased remote path: `${REGISTRY,,}/${GITHUB_REPOSITORY_OWNER,,}/${IMAGE_NAME}`.

**Caller-provided tooling:** this action does **not** install dependencies. Callers must provide `podman` and `jq` themselves (for example by running in a Wolfi container or on an Ubuntu runner that already has them available).

Population pattern:
- create the manifest locally with `podman manifest create`
- iterate `digests-json` with `jq` and add each digest using `podman manifest add ... --arch <platform>`
- apply newline-separated OCI annotations via `podman manifest annotate --index --annotation`; falls back to `buildah manifest annotate --annotation` when the runner ships podman < 5.0 (GitHub Actions runners ship 4.9.x and do not support `--index`)

Push pattern:
- push the **first** tag with `podman manifest push --all=false --digestfile ...` to capture the manifest-list digest
- push all remaining tags with `podman manifest push --all=false` so each alias tag is published without a separate digest-capture pass
- wrap each tag push in a small retry loop (3 attempts)

### `sign-and-publish`

Two signing modes:

- `keyless` (default): OIDC/Fulcio via `cosign sign -y`. **Requires** `id-token: write` in the calling job. Validated early — fails immediately if `ACTIONS_ID_TOKEN_REQUEST_URL` is unset.
- `key`: `cosign sign -y --key env://COSIGN_PRIVATE_KEY`. Requires `inputs.signing-key` to be set.

**Step order (important):** gen-sbom → GitHub SBOM attestation → ORAS attach → sign SBOM artifact → SLSA provenance attestation.

**SBOM flow** (when `generate-sbom: true`): Syft generates SPDX JSON → `actions/attest` with `sbom-path` creates a GitHub-native SBOM attestation in the attestation store → ORAS attaches the same SPDX JSON as an OCI referrer artifact → cosign signs the ORAS artifact digest. Both are needed: ORAS serves OCI-native consumers; the GitHub attestation store serves `gh attestation verify` and GitHub-native consumers.

**SLSA Build L2 provenance:** `actions/attest-build-provenance` (when `push-attestation: true`) emits the `https://slsa.dev/provenance/v1` predicate automatically from the OIDC token — capturing workflow ref, git SHA, trigger event, and runner environment. This satisfies SLSA Build L2 on GitHub-hosted runners. Self-hosted runners are **explicitly out of scope** — see `docs/skills/supply-chain.md`.

**Cosign verify scoping:** After the keyless image sign step, `cosign verify` runs immediately with `--certificate-identity-regexp` sourced from the `certificate-identity-regexp` input (default: `projectbluefin/(bluefin|bluefin-lts|aurora|actions)`). This is scoped to specific repos rather than the entire org to prevent a compromised org repo from passing verification. Callers outside the org must override the input with their own prefix.

**Retry policy:** All four `cosign sign` invocations (image keyless, image key-based, SBOM keyless, SBOM key-based) are wrapped with `nick-fields/retry` — 3 attempts, 30s wait between attempts, 5 min timeout per attempt. This reduces unsigned-image publishes from transient Rekor/TUF connectivity failures.

**Known workaround:** `sudo chown -R "$(id -u):$(id -g)" "${HOME}/.sigstore"` is needed before cosign operations — the sigstore cache directory sometimes has wrong ownership on GitHub-hosted runners.

Verify attestations after a build with:
```bash
gh attestation verify oci://ghcr.io/projectbluefin/bluefin@<digest> --repo projectbluefin/bluefin
```

### `rechunk`

Runs `rpm-ostree compose build-chunked-oci` **inside** the source image itself (privileged `podman run --rm --privileged`) with the host's `/var/lib/containers` volume mounted. Output lands in `containers-storage:localhost/<output-image>`.

⚠️ **Trust requirement:** The source image is executed as a privileged container with full access to host container storage. Only use `rechunk` with images you built in the same CI job or that come from a controlled registry. Never rechunk an image from an untrusted or external source.

`previous-build` enables delta optimization for smaller OTA updates. Pass the previous build's registry reference.

### `chunka`

OCI-native rechunking via [chunkah](https://github.com/coreos/chunkah). Uses `buildah build` with a **vendored** `Containerfile.splitter` — no rpm-ostree required.

Key design decisions:
- `CHUNKAH_VERSION`, `CHUNKAH_SHA`, and `bootc-build/chunka/Containerfile.splitter` are all version-pinned. **Bump all three together** when upgrading — see `docs/skills/supply-chain.md` for the step-by-step procedure.
- `Containerfile.splitter` is vendored at `bootc-build/chunka/Containerfile.splitter` and referenced by local path (`${{ github.action_path }}/Containerfile.splitter`). It is **never fetched from the network at build time** — fetching from a mutable release URL is a supply-chain attack vector.
- `CHUNKAH_CONFIG_STR=$(sudo podman inspect "${SOURCE}")` passes existing OCI labels through so `containers.bootc=1` and other metadata are preserved.
- Mandatory cleanup flags (`--prune /sysroot/ --label ostree.commit- --label ostree.final-diffid-`) strip stale OSTree annotations and are hardcoded — they are correctness requirements, not tuning knobs.
- `output-image` defaults to `source-image` (in-place rechunk).
- `force-compression` input is optional and defaults to `false` (preserves existing compression). Use `true` for images that must migrate from existing registry compression (e.g. CentOS Stream bases transitioning from gzip to zstd:chunked).

**Workarounds carried from consuming repos:**

| Workaround | Reason |
|---|---|
| `--skip-unused-stages=false` | buildah may skip the final import stage without this |
| `-v "$(pwd):/run/src"` + `--security-opt=label=disable` | Required for buildah < v1.44 (Ubuntu 24.04 ships 1.33.x) — keeps the `/run/src` bind-mount alive so `out.ociarchive` is findable by the final stage |
| `sudo rm -f out.ociarchive` | Containerfile.splitter leaves this artifact in the CWD; clean up to avoid stale files on re-runs |
| `sudo podman save "${OUTPUT_TAG}" \| podman load` | buildah runs as root; its container store is separate from the runner-user's podman store — pipe transfers the image to unprivileged podman |

**Root storage prerequisite:** `source-image` must be visible to rootful container storage (i.e., built or imported with `sudo`/buildah). Images built rootless won't be found by `sudo buildah build --from`.

### `ghcr-cleanup`

Thin wrapper around `dataaxiom/ghcr-cleanup-action`. Deletes untagged/old images older than `older-than` (default: 90 days), keeping at least `keep-n-tagged` and `keep-n-untagged` (both default: 7).

### `detect-changes`

Wraps `dorny/paths-filter` with configurable path filters. Eliminates duplicate path-filter blocks across `pr-validation.yml` and `build-image-testing.yml` in consuming repos, and centralizes the `dorny/paths-filter` pin so Renovate updates propagate via a single PR here.

Inputs:

| Input | Default | Description |
|---|---|---|
| `filters` | bluefin/aurora paths | Full `dorny/paths-filter` YAML defining `image` and `nvidia` filters. Override for repos with different path conventions. |

Outputs:

| Output | Description |
|---|---|
| `image_changed` | `true` if any image-affecting path changed |
| `should_build` | Alias for `image_changed` |
| `nvidia_changed` | `true` if Containerfile or the akmods kernel script changed |
| `image_flavors` | JSON array — `["main"]` or `["main","nvidia-open"]` |

**Standard usage (bluefin/aurora — no override needed):**

```yaml
detect-changes:
  runs-on: ubuntu-latest
  outputs:
    image_flavors: ${{ steps.detect.outputs.image_flavors }}
    should_build:  ${{ steps.detect.outputs.should_build }}
  steps:
    - uses: actions/checkout@...
    - uses: projectbluefin/actions/bootc-build/detect-changes@v1
      id: detect
```

**bluefin-lts override (build_scripts, image-versions.yaml):**

```yaml
    - uses: projectbluefin/actions/bootc-build/detect-changes@v1
      id: detect
      with:
        filters: |
          image:
            - 'Containerfile'
            - 'build_scripts/**'
            - 'system_files/**'
            - 'image-versions.yaml'
            - 'Justfile'
          nvidia:
            - 'Containerfile'
```

### `validate-pr`

Centralises all PR-validation action pins (hadolint, taiki-e/install-action, pre-commit). Previously each consumer had `hadolint/hadolint-action` and `taiki-e/install-action` (via a local `.github/actions/bootstrap-just/`) pinned inline, causing per-workflow Renovate bump PRs. With this action, Renovate updates happen once here; all consumers inherit the fix on their next SHA bump.

Steps executed in order:
1. Install `just` (via `taiki-e/install-action`)
2. Install `shellcheck` (apt)
3. Install `pre-commit` (pip)
4. Restore `~/.cache/pre-commit` from GHA cache (keyed by `runner.os + runner.arch + hashFiles('.pre-commit-config.yaml')`)
5. `just check`
6. `shellcheck` over `inputs.shellcheck-glob`
7. Optional `shellcheck` over `inputs.system-files-shellcheck-glob`
8. Optional `desktop-file-validate` over `system_files/**/*.desktop`
9. Optional submodule drift check for paths listed in `inputs.check-submodule-drift`
10. `hadolint/hadolint-action` with configurable dockerfile + config path
11. `pre-commit run --all-files`

Inputs:

| Input | Default | Description |
|---|---|---|
| `dockerfile` | `Containerfile` | Path to lint with hadolint |
| `hadolint-config` | `.hadolint.yaml` | hadolint config file |
| `shellcheck-glob` | `build_files/**/*.sh` | Shell scripts glob |
| `system-files-shellcheck-glob` | `""` | Optional additional shell glob for `system_files` scripts |
| `enable-desktop-file-validate` | `"false"` | Optional `desktop-file-validate` for `system_files/**/*.desktop` |
| `check-submodule-drift` | `""` | Optional comma-separated submodule paths to diff for manual edits |

**Consumer layout gotcha — `validate-pr` default glob is bluefin-specific:** The default `shellcheck-glob` is `build_files/**/*.sh`, which is the bluefin/aurora layout. Repos with different conventions must override:
- `bluefin-lts`: uses `build_scripts/**/*.sh` (not `build_files`)
- `bluefin` and `common` can opt into `system-files-shellcheck-glob`, `enable-desktop-file-validate`, and `check-submodule-drift` for stricter `system_files` validation without changing defaults for other consumers
- Pass `hadolint-config: ""` if the repo has no `.hadolint.yaml`

**Usage pattern:**

```yaml
- uses: projectbluefin/actions/bootc-build/validate-pr@v1
  # no inputs needed for standard bluefin/aurora layout
```

**When updating hadolint or taiki-e/install-action SHA pins:** edit only the pin in `bootc-build/validate-pr/action.yml`. All consuming repos pick up the update automatically when their `projectbluefin/actions` Renovate bump PR merges.

### `scan-image`

Wraps `aquasecurity/trivy-action` to scan a locally built OCI image for CVEs **before push**. Uploads SARIF results to the GitHub Security tab unconditionally (always, whether the scan passes or fails) so findings appear as annotations.

**Placement rule:** must run per-arch in the matrix build job, after `Tag Images` and **before** `Push to GHCR`. Scanning after push means shipping a known-critical image to the registry. This action is already wired into `reusable-build.yml` at the correct position.

Inputs:

| Input | Default | Description |
|---|---|---|
| `image` | required | Local image ref to scan (e.g. `localhost/bluefin:latest`) |
| `severity-threshold` | `CRITICAL` | Fail on this severity and above |
| `exit-code` | `1` | Set to `0` for report-only (no gate) — use on PR builds |
| `ignore-unfixed` | `true` | Skip vulns with no available fix |
| `github-token` | required | Token for SARIF upload |

In `reusable-build.yml`, `exit-code` is automatically `0` on `pull_request` events and `1` on push events. The `scan-severity-threshold` workflow input lets callers override the threshold (default: `CRITICAL`).

**Permission required:** the calling job needs `security-events: write` for SARIF upload. This is already set on the `build_container` job in `reusable-build.yml`.

### `generate-release-notes`

Wraps `orhun/git-cliff-action` to parse Conventional Commits and generate structured markdown changelogs. Requires a `cliff.toml` in the repo root (a factory-wide config is provided at the root of this repo and can be copied).

Inputs:

| Input | Default | Description |
|---|---|---|
| `tag` | required | Release tag to generate notes for (e.g. `v1.2.3`) |
| `output-file` | `CHANGELOG.md` | Path to write the changelog |
| `config` | `cliff.toml` | Path to cliff.toml |
| `github-token` | required | For GitHub-flavored commit links |

Outputs: `changelog` (file path), `content` (markdown string suitable as a GitHub Release body).

**Validate the tag input first:** before passing `inputs.tag` to git-cliff, add a small shell step that validates a semver-like tag pattern (for example `v1.2.3`, `1.2.3`, `v1.2.3-rc.1`). Pass the input through `env:` and fail with `::error::` on malformed values.

**Fetch depth:** git-cliff needs full commit history. Call with `fetch-depth: 0` when checking out.

Used by `reusable-release.yml` to automate GitHub Release creation on tag push. See "Reusable workflows" below.

### `validate-pr-title`

Validates that a PR title matches the Conventional Commits format required across all factory repos. Lives at `.github/actions/validate-pr-title/action.yml` (not `bootc-build/`).

Pattern enforced: `^(feat|fix|chore|docs|refactor|test|perf|ci|build|revert)(\(.+\))?: .+$`

Accepts an optional `custom-pattern` input for repos with stricter conventions. On failure, emits a clear error showing the failing title, the pattern, all valid types, and 5 concrete examples.

Consumer usage (call from any PR validation workflow):

```yaml
- uses: projectbluefin/actions/.github/actions/validate-pr-title@v1
  with:
    pr-title: ${{ github.event.pull_request.title }}
```

---

## Reusable workflows

The repo provides two reusable workflows:

| Workflow | Purpose |
|---|---|
| `.github/workflows/reusable-build.yml` | Full Fedora bootc image build pipeline (Path 1) |
| `.github/workflows/reusable-release.yml` | Changelog generation and GitHub Release creation |

### `reusable-build.yml` — calling from a consuming repo

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

### How action refs work inside the reusable workflow

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

### Tag generation and manifest scope

`reusable-build.yml` intentionally keeps tag generation in the caller repo by running `just generate-build-tags` instead of `bootc-build/generate-tags`. That is part of the Path 1 Justfile contract, alongside `image_name`, `generate-default-tag`, `build-ghcr`, and `tag-images`.

`bootc-build/generate-tags` exists for Path 2 / à la carte pipelines that want the shared default tag policy without adopting the full reusable workflow contract.

`bootc-build/create-manifest` is also a Path 2 building block today. The reusable workflow builds and pushes per-architecture images and emits digests, but it does **not** assemble or push a multi-arch manifest index; callers that need a manifest job should add an explicit follow-on `create-manifest` step in their own workflow.

### Digest output shape (multi-arch safe)

The `digests` output is a nested JSON map: `{ "image-name": { "platform": "digest" } }`. Platform keys use OCI names (`amd64`, `arm64`), mapped from runner architecture names (`x86_64`, `aarch64`) during artifact writing. Single-arch builds produce one platform key per image; multi-arch builds produce one per architecture.

This shape is directly compatible with `create-manifest`'s `digests-json` input — callers can iterate the outer map and pass each inner object to `create-manifest` without reshaping.

The digest artifact files use pipe-delimited format (`image_name|oci_platform|digest`) so that the `collect-digests` job can build the nested structure without key collisions across architectures.

### JSON array inputs

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

### SBOM artifact shape

The workflow stages SBOMs as `IMAGE_NAME.sbom.json` (flat rename from `sbom_out/IMAGE_NAME/sbom.json`) before upload. The `generate-release.yml` workflow expects this `*.sbom.json` glob shape.

SBOM generation and upload should run for every non-PR build, including the `testing` stream. Weekly promotions retag testing digests directly to production tags, so skipping SBOM on testing leaves promoted images without signed SBOM referrers.

### `reusable-release.yml` — calling from a consuming repo

```yaml
jobs:
  release:
    uses: projectbluefin/actions/.github/workflows/reusable-release.yml@v1
    secrets: inherit
    with:
      tag: ${{ github.ref_name }}   # e.g. v1.2.3
      # draft: false                # optional
      # prerelease: false           # optional
      # cliff-config: cliff.toml   # optional; defaults to repo root
```

The workflow checks out with `fetch-depth: 0` (required by git-cliff), runs `generate-release-notes`, and creates a GitHub Release with the generated body. The caller's repo needs `contents: write` — this is already granted in the workflow via `permissions: { contents: write }` on the `release` job.

**`cliff.toml` requirement:** a `cliff.toml` must exist in the caller's repo root (or override via `cliff-config` input). A factory-wide config is available at the root of this repo and can be copied verbatim.

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

### Line-count reduction targets

When refactoring a consumer workflow to use shared actions, the real metric is "inline blocks replaced" not absolute line count. Multi-arch matrix orchestration (the `generate_matrix` job, per-arch build matrix, conditional arm64 logic) stays in the consumer workflow — shared actions are per-arch steps, not matrix orchestrators. Account for this when estimating reduction. For example, a 611-line `reusable-build-image.yml` may reduce to ~412 lines after Phase A because the matrix stays; do not expect <250 lines.

### Force-compression input rationale

The `chunka` and `push-image` actions expose an optional `force-compression` input (default: `false`). This input exists for CentOS Stream 10 and other non-Fedora consumers that need to migrate existing registry layers from `gzip` to `zstd:chunked`. Fedora consumers should leave it at the default because Fedora images are already `zstd:chunked` and forcing recompression strips `ostree.components` layer annotations.

### Consumer validation flow

See [`consumer-validation.md`](consumer-validation.md) for the required before-merge protocol, blast-radius table, and out-of-org consumer guidance.

### Breaking change policy

If a breaking change is unavoidable:
- Option A: create a versioned subdirectory (`bootc-build/<name>/v2/action.yml`) and route new callers there while old callers keep `v1`
- Option B: coordinate a single wave — update all consuming repos in one PR sweep, then bump `@v1`

Document the blast radius (which repos, which inputs change) in the PR description. Do not merge without a link to passing CI in at least one consumer.

---

## Adding a new action

1. Create `bootc-build/<name>/action.yml`.
2. Pin all external `uses:` to commit SHAs with version comments.
3. Use the `env:` block pattern for all inputs passed to shell.
4. If the action downloads or references any external file (Containerfile, script, config) at runtime, vendor it or verify its SHA-256 — see `docs/skills/supply-chain.md`.
5. Add the action to the table in `README.md`.
6. Add a row to the skill routing table in `docs/SKILL.md`.
7. Add an entry to the action-by-action reference section above.
8. Add the action to the catalog table in `docs/skills/consumer-guide.md`.

---

## Common editing pitfalls

### Dropping `with:` when editing `uses:`

When you change only the SHA or comment on a `uses:` line, it's easy to accidentally delete the `with:` block below it. The result is a valid-looking YAML step where `uses:` runs but all inputs are silently dropped — actionlint catches this on push.

```yaml
# ❌ broken — with: block dropped, all inputs silently gone
- name: Upload artifact
  uses: actions/upload-artifact@abc123 # v7.0.1
    path: /tmp/output/               # ← this is now orphaned YAML, not under with:

# ✅ correct
- name: Upload artifact
  uses: actions/upload-artifact@abc123 # v7.0.1
  with:
    path: /tmp/output/
```

Always verify the `with:` block is still present after editing a `uses:` line. Actionlint enforces this but only on push — not in local editors.

---

## CI-fix-first workflow (for agents)

When an agent working in a **consuming repo** (bluefin, aurora, bazzite…) discovers a CI issue that involves duplicated inline steps or pinned third-party actions, the fix belongs **here first**:

1. **Check if an action already exists** — scan the catalog above. If the shared action doesn't exist yet, create it here (follow "Adding a new action" above).
2. **Open a PR in this repo** on a feature branch with the new or updated action.
3. **Open a draft PR in the consumer repo** pinned to the feature branch SHA (e.g. `projectbluefin/actions/bootc-build/detect-changes@<SHA>`). CI must pass there before this repo's PR merges.
4. **After this repo's PR merges** and `@v1` tag moves, update the consumer PR to `@v1`.

**What belongs here vs. in the consumer repo:**

| Belongs here (`projectbluefin/actions`) | Stays in the consumer repo |
|---|---|
| Shared step sequences (lint, validate, detect-changes) | Caller-specific permissions scoping |
| Third-party action pins (hadolint, install-action, paths-filter) | `secrets: inherit` decisions |
| Reusable logic used in ≥2 workflows or repos | Repo-specific Justfile recipes |
| Path-filter definitions shared across workflows | Workflow scheduling and triggers |

Never add a new inline `uses:` for a third-party action in a consumer workflow if that action is already wrapped here. Inline pins create Renovate drift across all consumer workflows — centralize them.

---

## Known workarounds

| Workaround | Location | Issue |
|---|---|---|
| `chown /run/user/$UID/containers` before login | `push-image`, `create-manifest` | Earlier `sudo podman login` can leave root-owned auth files that break later user-space login |
| `chmod 777` before cache save | `dnf-cache` | [actions/cache#1533](https://github.com/actions/cache/issues/1533) — root-owned files break cache agent |
| `chown ~/.sigstore` before cosign | `sign-and-publish` | Runner sigstore cache created with wrong ownership |
| podman upgraded from Ubuntu resolute | `setup-runner` | Ubuntu 24.04 podman too old for `ostree.components` annotations + `zstd:chunked` push |
| `-v $(pwd):/run/src` + `--security-opt=label=disable` | `chunka` | buildah < v1.44 drops bind-mounts without these; needed for `out.ociarchive` to survive to final stage |
| `sudo rm -f out.ociarchive` | `chunka` | Containerfile.splitter leaves artifact in CWD; stale file breaks re-runs |
| `sudo podman save \| podman load` | `chunka` | buildah (root) and podman (user) use separate container stores |
