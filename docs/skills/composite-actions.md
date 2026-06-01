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

Never use floating tags (`@main`, `@v3`, `@latest`). Renovate manages SHA bumps in consuming repos — but the canonical pins live here.

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

Restore behavior should include two fallback tiers: first `restore-keys: ${{ runner.os }}-${{ inputs.architecture }}-buildah-${{ inputs.cache-name }}-` for partial matches within the same flavor/version family, then the broader `restore-keys: ${{ runner.os }}-${{ inputs.architecture }}-buildah-` fallback.

Save behavior should be guarded with `always() && !cancelled()` so failed builds still persist downloaded packages for the next retry.

Cache key format: `Linux-<arch>-buildah-<cache-name>`.

### `preflight`

Validates registry auth, normalizes image refs to lowercase, and checks required secrets are non-empty.

Outputs `registry-lowercase` and `image-ref` (if `image-name` was supplied).

### `push-image`

Pushes with `zstd:chunked` compression using a **single** `sudo -E podman push` for the default tag. Default behavior must **not** pass `--force-compression`: rechunked Fedora images are already `zstd:chunked`, and forcing recompression strips `ostree.components` layer annotations.

For chunkah-based images that need to migrate existing registry layers from `gzip` to `zstd:chunked` (for example bluefin-lts), expose a `force-compression` input and conditionally append `--force-compression` inside the push loop via an env-backed shell flag.

Capture the pushed digest with `skopeo inspect --no-tags ... | jq -r '.Digest'` after the push instead of doing a second `podman push --digestfile` upload.

Before the user-space registry login, restore ownership of `/run/user/$(id -u)/containers` if it exists. Earlier `sudo podman login` calls in consuming workflows can leave root-owned auth files there and break the later unprivileged login. Keep this as an opt-out input (`fix-auth-permissions`, default `true`) so callers can disable it when unnecessary.

Alias tags are applied server-side via `skopeo copy` (no re-upload).

Retry logic: outer `while` loop up to `max-attempts` (default 3), with `retry-wait-seconds` (default 15s) between attempts. The inner `podman push` also carries `--retry 5 --retry-delay 30s`.

### `create-manifest`

Assembles and pushes a multi-arch OCI manifest index from a JSON map of `platform -> digest` values (for example `{"amd64":"sha256:...","arm64":"sha256:..."}`). The local manifest name should match the lowercased remote path: `${REGISTRY,,}/${GITHUB_REPOSITORY_OWNER,,}/${IMAGE_NAME}`.

**Caller-provided tooling:** this action does **not** install dependencies. Callers must provide `podman` and `jq` themselves (for example by running in a Wolfi container or on an Ubuntu runner that already has them available).

Population pattern:
- create the manifest locally with `podman manifest create`
- iterate `digests-json` with `jq` and add each digest using `podman manifest add ... --arch <platform>`
- apply newline-separated OCI annotations with `podman manifest annotate --index --annotation`

Push pattern:
- push the **first** tag with `podman manifest push --all=false --digestfile ...` to capture the manifest-list digest
- push all remaining tags with `podman manifest push --all=false` so each alias tag is published without a separate digest-capture pass
- wrap each tag push in a small retry loop (3 attempts)

### `sign-and-publish`

Two signing modes:

- `keyless` (default): OIDC/Fulcio via `cosign sign -y`. **Requires** `id-token: write` in the calling job. Validated early — fails immediately if `ACTIONS_ID_TOKEN_REQUEST_URL` is unset.
- `key`: `cosign sign -y --key env://COSIGN_PRIVATE_KEY`. Requires `inputs.signing-key` to be set.

SBOM flow (when `generate-sbom: true`): Syft generates SPDX JSON → ORAS attaches it to the registry → cosign signs the SBOM artifact itself.

After the keyless image sign step, immediately run `cosign verify` with GitHub repository identity and the GitHub Actions OIDC issuer to fail fast if the signature was not applied as expected.

**Known workaround:** `sudo chown -R "$(id -u):$(id -g)" "${HOME}/.sigstore"` is needed before cosign operations — the sigstore cache directory sometimes has wrong ownership on GitHub-hosted runners.

GitHub attestation pushed via `actions/attest` (always when `push-attestation: true`, regardless of signing mode).

### `rechunk`

Runs `rpm-ostree compose build-chunked-oci` **inside** the source image itself (privileged `podman run --rm --privileged`) with the host's `/var/lib/containers` volume mounted. Output lands in `containers-storage:localhost/<output-image>`.

`previous-build` enables delta optimization for smaller OTA updates. Pass the previous build's registry reference.

### `chunka`

OCI-native rechunking via [chunkah](https://github.com/coreos/chunkah). Uses `buildah build` with the upstream `Containerfile.splitter` — no rpm-ostree required.

Key design decisions:
- `CHUNKAH_VERSION` and `CHUNKAH_SHA` are defined once and derive both the image ref (`quay.io/coreos/chunkah:<VERSION>@<SHA>`) and the `Containerfile.splitter` URL. **Bump both together** when upgrading.
- `CHUNKAH_CONFIG_STR=$(sudo podman inspect "${SOURCE}")` passes existing OCI labels through so `containers.bootc=1` and other metadata are preserved.
- Mandatory cleanup flags (`--prune /sysroot/ --label ostree.commit- --label ostree.final-diffid-`) strip stale OSTree annotations and are hardcoded — they are correctness requirements, not tuning knobs.
- `output-image` defaults to `source-image` (in-place rechunk).

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

---

## Reusable workflow

The repo provides a complete reusable workflow at `.github/workflows/reusable-build.yml` for Fedora-based bootc image builds (bluefin, aurora, etc.).

### Calling from a consuming repo

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

### How local action refs work inside the reusable workflow

When a consuming repo calls the workflow:
- `github.repository` = the **caller's** repo (e.g. `projectbluefin/bluefin`)
- `actions/checkout` checks out the **caller's** code into `GITHUB_WORKSPACE`
- `just` commands run against the **caller's** Justfile — this is intentional
- `uses: ./bootc-build/...` refs inside the reusable workflow resolve in the **`actions` repo** at the called version — NOT in the caller's workspace

This means the workflow can always use the composite actions from this repo with relative paths, while the Justfile-driven build steps run caller-specific logic.

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

### Consumer validation flow

1. Land change on a **feature branch** in this repo
2. In one consumer repo (e.g. `projectbluefin/bluefin`), open a **draft PR** that pins `uses:` to the feature branch SHA
3. CI must pass on the consumer PR before the feature branch merges to `main` here
4. After `main` merge, move the `@v1` tag forward:
   ```bash
   git tag -f v1
   git push --force origin v1
   ```
5. Consumer PRs can then switch from the SHA pin to `@v1`

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
4. Add the action to the table in `README.md`.
5. Add a row to the skill routing table in `docs/SKILL.md`.
6. Add an entry to the action-by-action reference section above.

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
