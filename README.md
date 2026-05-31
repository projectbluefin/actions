# projectbluefin/actions

Shared GitHub Actions for bootc image builders. Used by [bluefin](https://github.com/projectbluefin/bluefin), [aurora](https://github.com/ublue-os/aurora), and [bazzite](https://github.com/ublue-os/bazzite).

# DESIGNED FOR UPSTREAM ADOPTION

These skills are the shared knowledge of 5 years of Universal Blue. The humans did such a good job that we were able to redo it with agents in a weekend. If you find an action here that should live in a CNCF or OpenSSF or any other upstream project and want to help, consider it your first quest!

Bluefin has testing branches and a passionate developer community, if you're an OSS maintainer and want a piece of tooling in here to live upstream, take it and we'll commit to CI for you. Another logo in your ADOPTERS.md. 


## Available Actions

| Action | Purpose |
|--------|---------|
| [`bootc-build/setup-runner`](bootc-build/setup-runner/) | Prepare runner: update podman, configure storage, install tools |
| [`bootc-build/dnf-cache`](bootc-build/dnf-cache/) | Restore/save DNF cache with permissions workaround |
| [`bootc-build/ghcr-cleanup`](bootc-build/ghcr-cleanup/) | Prune old GHCR images |
| [`bootc-build/preflight`](bootc-build/preflight/) | Validate runner environment before build |
| [`bootc-build/sign-and-publish`](bootc-build/sign-and-publish/) | Cosign sign + SBOM + attestation |
| [`bootc-build/rechunk`](bootc-build/rechunk/) | rpm-ostree rechunking for OTA deltas |
| [`bootc-build/chunka`](bootc-build/chunka/) | chunkah rechunking (OCI-native, no rpm-ostree) |
| [`bootc-build/push-image`](bootc-build/push-image/) | GHCR push with retry and digest capture |

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
