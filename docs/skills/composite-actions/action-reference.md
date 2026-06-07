---
name: composite-actions-reference
description: Full action-by-action reference for all bootc-build composite actions: setup-runner, dnf-cache, preflight, push-image, sign-and-publish, rechunk, chunka, ghcr-cleanup, detect-changes, validate-pr, scan-image, generate-release-notes, create-release, validate-pr-title, generate-tags, create-manifest. Load when implementing, debugging, or wiring a specific action.
metadata:
  type: reference
---

# Action-by-Action Reference

Detailed reference for each action in `bootc-build/`. For authoring conventions (SHA pinning, shell
patterns, github-token pattern), see the parent [`composite-actions.md`](../composite-actions.md).

## Contents
- [setup-runner](#setup-runner)
- [dnf-cache](#dnf-cache)
- [preflight](#preflight)
- [push-image](#push-image)
- [generate-tags](#generate-tags)
- [create-manifest](#create-manifest)
- [sign-and-publish](#sign-and-publish)
- [rechunk](#rechunk)
- [chunka](#chunka)
- [ghcr-cleanup](#ghcr-cleanup)
- [detect-changes](#detect-changes)
- [validate-pr](#validate-pr)
- [scan-image](#scan-image)
- [generate-release-notes](#generate-release-notes)
- [create-release](#create-release)
- [validate-pr-title](#validate-pr-title)

---

## `setup-runner`

Sets up a GitHub Actions runner for bootc image building. Two storage backends:

- `btrfs` (default): mounts a BTRFS volume at `/var/lib/containers` via `ublue-os/container-storage-action`
- `remove-software`: frees disk by nuking Android/Haskell/dotnet toolchains

Upgrades podman from Ubuntu **resolute** (25.04) because Ubuntu 24.04 runners ship a version too old to support layer annotations (`ostree.components`) and `zstd:chunked` push.

Installs optional tools (`just`, `cosign`, `oras`, `syft`) via `install-tools` JSON array input.

---

## `dnf-cache`

Wraps `actions/cache/restore` and `actions/cache/save` for the buildah layer cache at `/var/tmp/buildah-cache-*`.

**Known workaround:** cache save requires recursively `chmod 777` on every matching `/var/tmp/buildah-cache-*` directory before the save step — buildah may create multiple numbered cache directories, not just `-0`; see [actions/cache#1533](https://github.com/actions/cache/issues/1533). This is intentional, not a bug.

**Empty-glob guard (cold build):** the `chmod` loop must use `if [[ -d "$d" ]]; then ... fi` rather than `[[ -d "$d" ]] && cmd`. On a cold build where no `/var/tmp/buildah-cache-*` directory exists yet, bash expands the glob to the literal string, `[[ -d "..." ]]` returns false, and the `&&` chain propagates that as a non-zero exit even under `set -e`. The `if` form treats the false branch as a no-op.

Restore behavior should include two fallback tiers: first a flavor-scoped restore key (`${{ runner.os }}-${{ inputs.architecture }}-buildah-<flavor>-` when `image-flavor` is set, or `${{ runner.os }}-${{ inputs.architecture }}-buildah-<cache-name>-` otherwise) for partial matches within the same flavor/version family, then the broader `${{ runner.os }}-${{ inputs.architecture }}-buildah-` fallback.

Save behavior should be guarded with `always() && !cancelled()` so failed builds still persist downloaded packages for the next retry.

Cache key format: `Linux-<arch>-buildah-[<flavor>-]<cache-name>`. Pass `image-flavor` (e.g., `main`, `nvidia-open`) to partition caches per flavor and prevent cross-flavor pollution. The input is optional — callers that don't pass it fall back to the old format.

**Exposing `cache-hit` to the caller:** the composite exposes a `cache-hit` output (`steps.restore.outputs.cache-hit`). To read it in the calling workflow's telemetry/summary, give the `uses:` step an `id:` (e.g., `id: dnf-cache-restore`) and reference `steps.dnf-cache-restore.outputs.cache-hit`. Without the `id`, the output is silently empty.

---

## `preflight`

Validates registry auth, normalizes image refs to lowercase, and checks required secrets are non-empty.

Outputs `registry-lowercase` and `image-ref` (if `image-name` was supplied).

---

## `push-image`

Pushes using a configurable `compression-format` (default `zstd:chunked`) via a **single** `sudo -E podman push` for the default tag. Default behavior must **not** pass `--force-compression`: rechunked Fedora images are already `zstd:chunked`, and forcing recompression strips `ostree.components` layer annotations.

The `compression-format` input controls `--compression-format` on `podman push`. Use the default (`zstd:chunked`) for Fedora/rpm-ostree consumers. Use `zstd` for BST-based consumers like dakota that export plain OCI tarballs without chunked layer annotations.

For chunkah-based images that need to migrate existing registry layers from `gzip` to `zstd:chunked` (for example bluefin-lts), expose a `force-compression` input and conditionally append `--force-compression` inside the push loop via an env-backed shell flag.

Capture the pushed digest with `skopeo inspect --no-tags ... | jq -r '.Digest'` after the push instead of doing a second `podman push --digestfile` upload.

Before the user-space registry login, restore ownership of `/run/user/$(id -u)/containers` if it exists. Earlier `sudo podman login` calls in consuming workflows can leave root-owned auth files there and break the later unprivileged login. Keep this as an opt-out input (`fix-auth-permissions`, default `true`) so callers can disable it when unnecessary.

Alias tags are applied server-side via `skopeo copy` (no re-upload).

Retry logic: outer `while` loop up to `max-attempts` (default 3), with `retry-wait-seconds` (default 15s) between attempts. The inner `podman push` also carries `--retry 5 --retry-delay 30s`.

---

## `generate-tags`

Generates the shared Fedora/Bluefin-style OCI alias tags from the built image's `org.opencontainers.image.version` label plus GitHub event context. Use this in **Path 2** or other custom pipelines that want the repo's stock tag policy without depending on a consumer Justfile.

The reusable workflow intentionally does **not** call this action. **Path 1** keeps tag generation inside the caller's Justfile contract via `just generate-build-tags`, so consuming repos retain control over tag policy and can evolve it without changing shared workflow wiring.

---

## `create-manifest`

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

---

## `sign-and-publish`

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

---

## `rechunk`

Runs `rpm-ostree compose build-chunked-oci` **inside** the source image itself (privileged `podman run --rm --privileged`) with the host's `/var/lib/containers` volume mounted. Output lands in `containers-storage:localhost/<output-image>`.

⚠️ **Trust requirement:** The source image is executed as a privileged container with full access to host container storage. Only use `rechunk` with images you built in the same CI job or that come from a controlled registry. Never rechunk an image from an untrusted or external source.

`previous-build` enables delta optimization for smaller OTA updates. Pass the previous build's registry reference.

---

## `chunka`

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

---

## `ghcr-cleanup`

Thin wrapper around `dataaxiom/ghcr-cleanup-action`. Deletes untagged/old images older than `older-than` (default: 90 days), keeping at least `keep-n-tagged` and `keep-n-untagged` (both default: 7).

---

## `detect-changes`

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
  runs-on: ubuntu-24.04
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

---

## `validate-pr`

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

**Pinning rule for PR tooling:** treat `.pre-commit-config.yaml` hook repos and `validate-pr` package installs with the same supply-chain discipline as `uses:` lines. External pre-commit hook repos must use full commit SHAs with inline release comments, `pre-commit` must be installed at an exact version while clearing inherited `PIP_CONSTRAINT` values from consumer repos, and `shellcheck` must be pinned to the Ubuntu 24.04 package version used by GitHub runners.

---

## `scan-image`

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

---

## `generate-release-notes`

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

Used by `reusable-release.yml` to automate GitHub Release creation on tag push. See [`reusable-workflow.md`](reusable-workflow.md).

---

## `create-release`

Creates a GitHub Release backed by a full supply chain story: SBOM diff,
release card (light + dark PNG), and step-by-step user-facing verification
instructions using CNCF / OpenSSF tools.

**This is the factory-standard release action for bluefin, bluefin-lts, and
dakota.** It replaces the per-repo `changelogs.py`, `hanthor/changelog-action`,
and `sbom_diff.py + render_card.py` scripts.

### Flow

```
calling workflow
  └─ download current SBOM artifact (already produced by sign-and-publish)
       └─ bootc-build/create-release
            1. validate SBOM (spdxVersion check)
            2. fetch previous SBOM from last GitHub Release (*.spdx.json asset)
            3. sbom_diff.py  → versions.json  (added / changed / removed)
            4. render_card.py → release-card.png + release-card-dark.png
            5. render_notes.py → release-notes.md
                 • key components table (notable packages)
                 • collapsible full SPDX package inventory
                 • supply chain section (cosign, oras, slsa-verifier)
            6. gh release create (attaches card PNGs + SBOM)
```

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `sbom-path` | ✅ | — | Path to current SPDX-JSON SBOM on disk |
| `tag` | ✅ | — | Release tag to create |
| `title` | ✅ | — | Release title |
| `image` | ✅ | — | Full image ref (no tag), e.g. `ghcr.io/projectbluefin/bluefin` |
| `digest` | ✅ | — | Image digest (`sha256:...`) for verification instructions |
| `repo` | ✅ | — | `org/repo` slug |
| `notable-packages` | ✅ | — | JSON array: `[{"sbom_name":"linux","label":"Kernel"},...]` |
| `cert-identity-regexp` | ✅ | — | cosign `--certificate-identity-regexp` for user-facing instructions |
| `github-token` | ✅ | — | Token with `contents: write` |
| `project-name` | | `Bluefin` | Display name on the release card |
| `accent-color` | | `#0ea5e9` | CSS colour for the card accent stripe |
| `badge-label` | | `Stable` | Badge text on the card (e.g. `LTS`, `Alpha`) |
| `docs-url` | | `https://docs.projectbluefin.io/changelogs` | Footer and supply chain link |
| `sbom-filename` | | basename of `sbom-path` | Asset filename attached to the release |
| `draft` | | `false` | Create as draft |
| `prerelease` | | `false` | Mark as pre-release |

Outputs: `release-url` (URL of the created release).

### Supply chain verification section (user-facing)

The generated `release-notes.md` always includes a **Supply chain** section
with four numbered steps, each using a CNCF / OpenSSF tool:

1. **`cosign verify`** — image keyless signature (Sigstore)
2. **`oras discover` + `oras pull`** — SBOM OCI referrer (CNCF ORAS, graduated)
3. **`cosign verify-attestation --type https://spdx.dev/Document`** — GitHub SBOM attestation
4. **`slsa-verifier verify-image`** — SLSA Build L2 provenance (OpenSSF) +
   `cosign verify-attestation --type slsaprovenance1` as the Sigstore path

All install via `brew install cosign oras slsa-verifier`.

### Per-repo `notable-packages` examples

**bluefin / bluefin-lts:**
```json
[
  {"sbom_name": "kernel", "label": "Kernel"},
  {"sbom_name": "gnome-shell", "label": "GNOME"},
  {"sbom_name": "mesa-filesystem", "label": "Mesa"},
  {"sbom_name": "podman", "label": "Podman"},
  {"sbom_name": "nvidia-driver", "label": "Nvidia"}
]
```

**dakota (BST — uses `spdxid_filter` to pick the right linux entry):**
```json
[
  {"sbom_name": "linux", "label": "Kernel", "spdxid_filter": "components-linux.bst"},
  {"sbom_name": "gnome-shell", "label": "GNOME"},
  {"sbom_name": "mesa", "label": "Mesa"},
  {"sbom_name": "podman", "label": "Podman"},
  {"sbom_name": "bootc", "label": "bootc"},
  {"sbom_name": "ghostty", "label": "ghostty"}
]
```

### Calling from a consumer workflow

The caller is responsible for downloading the SBOM artifact produced by the
build job before calling this action:

```yaml
- name: Download current SBOM
  uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8
  with:
    name: sbom-${{ env.IMAGE_NAME }}
    path: sbom-current

- name: Create release
  uses: projectbluefin/actions/bootc-build/create-release@v1
  with:
    sbom-path:             sbom-current/sbom.json
    tag:                   ${{ steps.meta.outputs.tag }}
    title:                 ${{ steps.meta.outputs.title }}
    image:                 ghcr.io/projectbluefin/bluefin
    digest:                ${{ steps.build.outputs.digest }}
    repo:                  ${{ github.repository }}
    notable-packages:      '[{"sbom_name":"kernel","label":"Kernel"},...]'
    cert-identity-regexp:  '^https://github\.com/projectbluefin/(bluefin|actions)/\.github/workflows/'
    project-name:          Bluefin
    accent-color:          "#0ea5e9"
    badge-label:           Stable
    sbom-filename:         bluefin.spdx.json
    github-token:          ${{ secrets.GITHUB_TOKEN }}
```

**Accent colours by repo:**
- bluefin: `#0ea5e9` (sky blue)
- bluefin-lts: `#0ea5e9` (sky blue)
- dakota: `#7c3aed` (purple)

---

## `validate-pr-title`

Validates that a PR title matches the Conventional Commits format required across all factory repos. Lives at `.github/actions/validate-pr-title/action.yml` (not `bootc-build/`).

Pattern enforced: `^(feat|fix|chore|docs|refactor|test|perf|ci|build|revert)(\(.+\))?: .+$`

Accepts an optional `custom-pattern` input for repos with stricter conventions. On failure, emits a clear error showing the failing title, the pattern, all valid types, and 5 concrete examples.

Consumer usage (call from any PR validation workflow):

```yaml
- uses: projectbluefin/actions/.github/actions/validate-pr-title@v1
  with:
    pr-title: ${{ github.event.pull_request.title }}
```
