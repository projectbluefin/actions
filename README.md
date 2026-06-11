# projectbluefin/actions

Shared GitHub Actions for bootc image builders. Used by [bluefin](https://github.com/projectbluefin/bluefin), [aurora](https://github.com/ublue-os/aurora), and [bazzite](https://github.com/ublue-os/bazzite).

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/projectbluefin/actions/badge)](https://scorecard.dev/viewer/?uri=github.com/projectbluefin/actions)

# DESIGNED FOR UPSTREAM ADOPTION

These skills are the shared knowledge of 5 years of Universal Blue. The humans did such a good job that we were able to redo it with agents in a weekend. If you find an action here that should live in a CNCF or OpenSSF or any other upstream project and want to help, consider it your first quest!

Bluefin has testing branches and a passionate developer community, if you're an OSS maintainer and want a piece of tooling in here to live upstream, take it and we'll commit to CI for you. Another logo in your ADOPTERS.md.


Maintainers: see [docs/MAINTAINERS.md](docs/MAINTAINERS.md) for the agentic workflow, review gates, and on-call runbook.

For private vulnerability reporting, see [SECURITY.md](SECURITY.md).

## Available Actions

| Action | Purpose |
|--------|---------|
| [`bootc-build/setup-runner`](bootc-build/setup-runner/) | Prepare runner: update podman, configure storage, install tools |
| [`bootc-build/dnf-cache`](bootc-build/dnf-cache/) | Restore/save DNF cache with permissions workaround |
| [`bootc-build/ghcr-cleanup`](bootc-build/ghcr-cleanup/) | Prune old GHCR images |
| [`bootc-build/preflight`](bootc-build/preflight/) | Validate runner environment before build |
| [`bootc-build/detect-changes`](bootc-build/detect-changes/) | Detect changed paths and compute the image-flavor build matrix |
| [`bootc-build/validate-pr`](bootc-build/validate-pr/) | Validate a PR: just check, shellcheck, hadolint, pre-commit |
| [`bootc-build/generate-tags`](bootc-build/generate-tags/) | Generate OCI image tags from stream, version, and event context |
| [`bootc-build/push-image`](bootc-build/push-image/) | GHCR push with retry and digest capture |
| [`bootc-build/create-manifest`](bootc-build/create-manifest/) | Assemble and push a multi-arch OCI image manifest index |
| [`bootc-build/sign-and-publish`](bootc-build/sign-and-publish/) | Cosign sign + SBOM + SLSA Build L2 provenance attestation |
| [`bootc-build/scan-image`](bootc-build/scan-image/) | Trivy CVE scan before push; uploads SARIF and can auto-file CVE issues on projectbluefin main builds |
| [`bootc-build/rechunk`](bootc-build/rechunk/) | rpm-ostree rechunking for OTA deltas |
| [`bootc-build/chunka`](bootc-build/chunka/) | chunkah rechunking (OCI-native, no rpm-ostree) |
| [`bootc-build/generate-release-notes`](bootc-build/generate-release-notes/) | git-cliff Conventional Commits changelog |

### Utility actions

| Action | Purpose |
|--------|---------|
| [`.github/actions/validate-pr-title`](.github/actions/validate-pr-title/) | Enforce Conventional Commits PR title format |

## Reusable Workflows

| Workflow | Purpose |
|--------|---------|
| [`.github/workflows/reusable-build.yml`](.github/workflows/reusable-build.yml) | Full Fedora bootc image build pipeline (Path 1) |
| [`.github/workflows/reusable-release.yml`](.github/workflows/reusable-release.yml) | Image stable-release orchestration and Conventional Commits GitHub Release creation |

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
