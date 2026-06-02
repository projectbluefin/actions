# projectbluefin/actions

Shared GitHub Actions for bootc image builders. Used by [bluefin](https://github.com/projectbluefin/bluefin), [aurora](https://github.com/ublue-os/aurora), and [bazzite](https://github.com/ublue-os/bazzite).

## Reusable Workflows

| Workflow | Purpose |
|----------|---------|
| [`.github/workflows/reusable-build.yml`](.github/workflows/reusable-build.yml) | Full Fedora bootc image build pipeline (bluefin, aurora) |

### Calling the reusable workflow

```yaml
jobs:
  build:
    uses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1
    secrets: inherit
    with:
      brand_name: bluefin
      stream_name: stable           # stable | latest | beta | testing
      image_flavors: '["main", "nvidia-open"]'
      architecture: '["x86_64"]'
```

Outputs a `digests` JSON map (`image_name → sha256:...`) for downstream signing and release jobs.

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
| [`bootc-build/create-manifest`](bootc-build/create-manifest/) | OCI multi-arch manifest assembly and push |

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
- **Onboarding a new image:** [`docs/skills/consumer-guide.md`](docs/skills/consumer-guide.md)
