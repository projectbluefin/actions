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

**Known workaround:** cache save requires `sudo chmod 777 --recursive /var/tmp/buildah-cache-0` before the save step — see [actions/cache#1533](https://github.com/actions/cache/issues/1533). This is intentional, not a bug.

Cache key format: `Linux-<arch>-buildah-<cache-name>`.

### `preflight`

Validates registry auth, normalizes image refs to lowercase, and checks required secrets are non-empty.

Outputs `registry-lowercase` and `image-ref` (if `image-name` was supplied).

### `push-image`

Pushes with `zstd:chunked` compression. Uses a **two-push pattern** for the default tag — two sequential `podman push` calls, the second with `--digestfile`. This works around a podman bug ([#27796](https://github.com/containers/podman/issues/27796)) where layer annotations are dropped in a single push.

Alias tags are applied server-side via `skopeo copy` (no re-upload).

Retry logic: outer `while` loop up to `max-attempts` (default 3), with `retry-wait-seconds` (default 15s) between attempts. The inner `podman push` also carries `--retry 5 --retry-delay 30s`.

### `sign-and-publish`

Two signing modes:

- `keyless` (default): OIDC/Fulcio via `cosign sign -y`. **Requires** `id-token: write` in the calling job. Validated early — fails immediately if `ACTIONS_ID_TOKEN_REQUEST_URL` is unset.
- `key`: `cosign sign -y --key env://COSIGN_PRIVATE_KEY`. Requires `inputs.signing-key` to be set.

SBOM flow (when `generate-sbom: true`): Syft generates SPDX JSON → ORAS attaches it to the registry → cosign signs the SBOM artifact itself.

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
| Two-push for digest capture | `push-image` | [podman#27796](https://github.com/containers/podman/issues/27796) — annotations dropped on single push |
| `chmod 777` before cache save | `dnf-cache` | [actions/cache#1533](https://github.com/actions/cache/issues/1533) — root-owned files break cache agent |
| `chown ~/.sigstore` before cosign | `sign-and-publish` | Runner sigstore cache created with wrong ownership |
| podman upgraded from Ubuntu resolute | `setup-runner` | Ubuntu 24.04 podman too old for `ostree.components` annotations + `zstd:chunked` push |
| `-v $(pwd):/run/src` + `--security-opt=label=disable` | `chunka` | buildah < v1.44 drops bind-mounts without these; needed for `out.ociarchive` to survive to final stage |
| `sudo rm -f out.ociarchive` | `chunka` | Containerfile.splitter leaves artifact in CWD; stale file breaks re-runs |
| `sudo podman save \| podman load` | `chunka` | buildah (root) and podman (user) use separate container stores |
