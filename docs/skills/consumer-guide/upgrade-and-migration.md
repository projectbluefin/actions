---
name: upgrade-and-migration-tests
description: Upgrade test and migration test reusable workflows for bootc image repos. Upgrade-test boots the image in QEMU and runs the lifecycle suite (upgrade, rollback, /etc persistence, idempotency). Migration-test validates the ublue-os→projectbluefin registry transition via bootc switch. Load when wiring post-build gates or troubleshooting test failures.
metadata:
  type: reference
---

# Upgrade and Migration Tests

Post-build gate workflows for bootc image repos. Both workflows are part of the
`projectbluefin/actions` reusable workflow catalog.

## Contents
- [Upgrade test](#upgrade-test)
- [Migration test](#migration-test)
- [Dakota (Path 2 only consumer)](#dakota-path-2-only-consumer)
- [Live consumer examples](#live-consumer-examples)

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

## Migration test

A cross-registry migration gate for the `ublue-os/bluefin[-lts]` → `projectbluefin/bluefin[-lts]` transition. Boots the **source** image in QEMU, switches to the **target** via `bootc switch`, and validates the full `@migration` scenario matrix from `projectbluefin/testsuite`.

Use this gate when validating that users migrating from the ublue-os registry to the projectbluefin registry land on a working system, including across the chunkah format boundary (legacy rpm-ostree rechunked layers → chunkah OCI-native layers).

### Minimal wiring — build → migration gate → promote

```yaml
jobs:
  build:
    outputs:
      digest: ${{ steps.push.outputs.digest }}

  migration-test:
    needs: build
    uses: projectbluefin/actions/.github/workflows/migration-test.yml@v1
    permissions:
      contents: read
      packages: write
    with:
      source_image: ghcr.io/ublue-os/bluefin-lts:lts
      migration_target: ghcr.io/projectbluefin/bluefin-lts@${{ needs.build.outputs.digest }}

  promote:
    needs: migration-test
    if: needs.migration-test.outputs.result == 'success'
```

### Inputs reference

| Input | Required | Default | Description |
|---|---|---|---|
| `source_image` | **yes** | — | Full OCI ref to boot as the migration source (an `ublue-os/bluefin` or `ublue-os/bluefin-lts` image) |
| `migration_target` | no | `""` | Full OCI ref to migrate TO. Empty = testsuite default (`projectbluefin/bluefin:stable`). Pass a pinned digest to gate on a specific freshly-built image |
| `chunked_enabled` | no | `false` | Enable `@zstd_chunked` migration scenarios. Set `true` once the target image ships zstd:chunked layers |

### Outputs reference

| Output | Description |
|---|---|
| `result` | Job outcome: `success`, `failure`, `cancelled`, or `skipped` |

### Migration scenarios validated

| Scenario | Notes |
|---|---|
| `bootc switch` → reboot → confirm target | Core migration path |
| `bootc rollback` → confirm source | Migration is reversible |
| System identity/health after migration | `os-release`, `bootc status` |
| Rollback digest preserved across chunkah boundary | No digest corruption |
| Unified storage lane | `--experimental-unified-storage` |
| Unified storage rollback | |
| zstd:chunked lane | Only when `chunked_enabled: true` |

Source: [`tests/lifecycle/features/migration.feature`](https://github.com/projectbluefin/testsuite/blob/main/tests/lifecycle/features/migration.feature)

---

## Dakota (Path 2 only consumer)

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

## Live consumer examples

### bluefin (Path 1 — extended validate-pr)

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

### bluefin-lts (Path 2 — CentOS Stream 10)

bluefin-lts uses CentOS Stream 10 (non-Fedora base) and cannot use the full reusable workflow. Key overrides:

| Action | Override | Why |
|---|---|---|
| `validate-pr` | `shellcheck-glob: "build_scripts/**/*.sh"` | lts uses `build_scripts/`, not `build_files/` |
| `detect-changes` | `filters:` with `build_scripts/**`, `image-versions.yaml` | default paths are bluefin-specific |
| `chunka` | `force-compression: true` | CentOS base must migrate gzip layers to zstd:chunked — passes `--compression-format zstd:chunked --force-compression` to `buildah build` |

This is the reference implementation for any bootc image repo that diverges from the bluefin path convention.
