# projectbluefin/actions

Shared GitHub Actions for bootc image builders. Used by [bluefin](https://github.com/projectbluefin/bluefin), [aurora](https://github.com/ublue-os/aurora), and [bazzite](https://github.com/ublue-os/bazzite).

## Available Actions

### P0 — Foundation

| Action | Purpose |
|--------|---------|
| [`bootc-build/setup-runner`](bootc-build/setup-runner/) | Prepare runner: update podman, configure storage, install tools |
| [`bootc-build/dnf-cache`](bootc-build/dnf-cache/) | Restore/save DNF cache with permissions workaround |
| [`bootc-build/ghcr-cleanup`](bootc-build/ghcr-cleanup/) | Prune old GHCR images |

### P1 — Core Pipeline (coming soon)

| Action | Purpose |
|--------|---------|
| `bootc-build/preflight` | Validate runner environment before build |
| `bootc-build/sign-and-publish` | Cosign sign + SBOM + attestation |
| `bootc-build/rechunk` | rpm-ostree rechunking for OTA deltas |
| `bootc-build/push-image` | GHCR push with retry and digest capture |

### P2 — Polish (coming soon)

| Action | Purpose |
|--------|---------|
| `bootc-build/generate-tags` | OCI image tag generation |
| `bootc-build/generate-release` | Changelog and GitHub release |

## Quick Start

```yaml
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      
      - uses: projectbluefin/actions/bootc-build/setup-runner@v1
        with:
          install-tools: '["just", "cosign", "oras"]'
      
      - uses: projectbluefin/actions/bootc-build/dnf-cache@v1
        with:
          action: restore
          cache-name: my-image-42
      
      - run: just build-ghcr
      
      - uses: projectbluefin/actions/bootc-build/dnf-cache@v1
        with:
          action: save
          cache-name: my-image-42
```

## Versioning

Pin to `@v1` for stability. Renovate manages updates in consuming repos.

## Related

- Epic: [projectbluefin/bluefin#134](https://github.com/projectbluefin/bluefin/issues/134)
