---
name: supply-chain
description: Secures the bootc image build supply chain. Covers vendoring external build files (Containerfiles, scripts), SLSA Build L2 posture and verification, cosign verify scoping, shift-left CVE scanning with Trivy (including secret scanning), and SBOM attestation patterns.
metadata:
  type: reference
---

# Supply Chain Security

Authoring and verification reference for the shared bootc-build action toolkit.

---

## Pattern: vendor external build instruction files

**Never fetch build instruction files (Containerfiles, scripts) from the network at build time.**
A mutable URL is a supply-chain attack vector — a compromised release asset runs arbitrary `RUN`
steps as `sudo` inside the OS image, then gets signed with a valid cosign signature and a clean SBOM.
The audit trail would show a fully legitimate image containing a backdoor.

### Rule

External build instruction files (e.g. `Containerfile.splitter` used by `chunka`) must be:

- **Vendored** into the action directory at a known commit, OR
- **Hash-verified** before use (`sha256sum -c`).

The vendored file path, its SHA-256, and the upstream version pin must all be bumped together in the
same commit on every version update.

### Implementation — chunka

`bootc-build/chunka/Containerfile.splitter` is vendored from the chunkah project. The action
references it by local path (`${{ github.action_path }}/Containerfile.splitter`) so no network
fetch happens at build time. The expected SHA-256 is recorded in a comment in `action.yml`.

**Renovate tracking (fully automated):** `renovate.json` has a custom regex manager that watches
`bootc-build/chunka/action.yml` and opens a PR when a new `quay.io/coreos/chunkah` digest/tag
is available. The `.github/workflows/vendor-chunka-files.yml` workflow automatically downloads
the matching `Containerfile.splitter` from the chunkah GitHub release, updates the SHA-256
comment in `action.yml`, and commits both back to the Renovate branch. When CI passes, the PR
automerges.

**No manual steps are required for routine chunkah upgrades.**

If the `Containerfile.splitter` changes in a way that requires coordinated changes to `action.yml`
(e.g. a new output format — this happened between v0.5.0 and v0.6.0 where `oci-archive:out.ociarchive`
became `oci:out`), the vendor workflow will commit the new file but CI may fail, signalling that
`action.yml` also needs a manual update. The skill file change and action.yml fix should be done in a
single follow-up commit on the Renovate branch before merging.

---

## Pattern: pin OCI images to the manifest index digest, not a platform digest

When pinning a container image to a SHA-256 digest (e.g. `CHUNKAH_SHA` in `chunka`), always
use the **manifest index (multi-arch) digest**, not a platform-specific digest.

**Why this matters:**

- Renovate's `docker` datasource tracks the manifest index digest. If the code uses a
  platform-specific digest, Renovate will immediately open a follow-up PR to "upgrade" the same
  version — the digests differ even though the image hasn't changed.
- The index digest works across architectures: `podman`/`buildah` resolve it to the correct
  platform automatically. A platform-specific digest fails on a different arch.

**How to get the correct digest:**

```bash
# Gets the index digest (correct)
skopeo inspect --no-tags docker://quay.io/coreos/chunkah:v0.6.0 | jq -r .Digest
# or via curl:
curl -sI "https://quay.io/v2/coreos/chunkah/manifests/v0.6.0" \
  -H "Accept: application/vnd.oci.image.index.v1+json" | grep -i docker-content-digest
```

**How to spot the wrong digest:**

```bash
# Shows the index + per-platform digests
curl -s "https://quay.io/v2/coreos/chunkah/manifests/v0.6.0" \
  -H "Accept: application/vnd.oci.image.index.v1+json" | jq '.manifests[] | {platform, digest}'
# If your pinned SHA matches one of these platform entries, you have a platform digest — fix it.
```

---

## Pattern: use `actions/attest-build-provenance` for SLSA provenance

Use `actions/attest-build-provenance` (not the generic `actions/attest`) for SLSA-compliant
build provenance. The generic `actions/attest` with no `predicate-type` or `sbom-path` creates a
cryptographically signed shell with **no payload** and does not satisfy SLSA Build L2.

`actions/attest-build-provenance` automatically emits the
`https://slsa.dev/provenance/v1` predicate from the OIDC token, capturing:

- Workflow ref and git SHA
- Build trigger event
- Runner environment

No additional secrets are required beyond the existing `id-token: write` +
`attestations: write` permissions already present in `reusable-build.yml`.

For **GitHub-native SBOM attestation** (discoverable via `gh attestation verify`), use
`actions/attest` with `sbom-path` pointing to the Syft-generated SPDX-JSON file. This is
**complementary to** the ORAS referrer attachment — both are needed (ORAS for OCI-native consumers,
GitHub attestation store for GitHub-native consumers).

---

## SLSA Build L2 posture

### Scope

| Build path | SLSA Build L2 capable? |
|---|---|
| Path 1 — `reusable-build.yml` on **GitHub-hosted runners** | ✅ Yes |
| Path 2 — à la carte composite actions on **GitHub-hosted runners** | ✅ Yes (caller must add `actions/attest-build-provenance`) |
| Path 1 or 2 on **self-hosted runners** | ❌ No — self-hosted runners are outside the GitHub-controlled build platform |

SLSA Build L2 requires a **hosted build platform** that controls the build environment. Composite
actions are environment-agnostic — they run wherever the caller's workflow runs. Callers on
self-hosted runners do **not** get SLSA Build L2 provenance even with `attest-build-provenance`
in the workflow.

### Verification

To verify SLSA provenance for an image built via `reusable-build.yml` on GitHub-hosted runners:

```bash
gh attestation verify oci://ghcr.io/projectbluefin/bluefin@<digest> --repo projectbluefin/bluefin
```

Both attestation types should appear:
- `sigstore/cosign/predicate/sbom` — GitHub SBOM attestation (from `actions/attest` + `sbom-path`)
- `https://slsa.dev/provenance/v1` — SLSA Build L2 provenance (from `actions/attest-build-provenance`)

### Downstream enforcement policy

Signing without a verification policy is theater. Consumers should verify attestations at promotion
boundaries:

```yaml
# Example: verify attestation before promoting to production
- name: Verify SLSA provenance before promotion
  run: |
    gh attestation verify oci://${{ env.IMAGE_REGISTRY }}/${{ env.IMAGE_NAME }}@${{ env.DIGEST }} \
      --repo ${{ github.repository }}
```

Wire this into the promotion workflow immediately before the environment gate. The
`environment: production` gate must come **after** verification, not before.

---

## Pattern: scope cosign verify to specific repos

The `--certificate-identity-regexp` flag in `cosign verify` must be scoped to specific known
signing workflows, not the entire organization. An org-wide regexp
(`https://github.com/myorg/`) matches every workflow in every repo in the org — including
compromised repos.

The `sign-and-publish` action exposes a `certificate-identity-regexp` input with a default
scoped to known bluefin/aurora signing workflows:

```
https://github.com/projectbluefin/(bluefin|bluefin-lts|aurora|actions)/.github/workflows/
```

Callers outside the `projectbluefin` org must override this input with their own org prefix.

---

## Pattern: shift-left CVE scanning

Run Trivy **per-arch in the matrix build job, before push** — not only on the final manifest
after push. Rationale:

- Each arch produces a distinct layer set; CRITICAL CVEs can exist in one arch but not the other.
- Scanning before push is the correct OpenSSF shift-left position: do not ship a known-critical
  image to the registry.
- PR builds scan in report-only mode (`exit-code: 0`); push events gate the build.

The `bootc-build/scan-image` composite action wraps `aquasecurity/trivy-action` and uploads
SARIF results to the GitHub Security tab (always, even when the scan passes).

Wire it into `reusable-build.yml` between `Tag Images` and `Push to GHCR`:

```yaml
- name: Scan image for vulnerabilities
  uses: projectbluefin/actions/bootc-build/scan-image@<sha>
  with:
    image: ${{ env.IMAGE_NAME }}:${{ env.DEFAULT_TAG }}
    severity-threshold: ${{ inputs.scan-severity-threshold }}
    exit-code: ${{ github.event_name == 'pull_request' && '0' || '1' }}
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

The `build_container` job must have `security-events: write` permission for SARIF upload.

### Secret scanning

`scan-image` also runs Trivy's secret scanner in two modes:

- **`scanners: vuln,secret`** — scans all filesystem layers for accidentally committed secrets
  (API keys, tokens, private keys, credential files).
- **`image-config-scanners: secret`** — scans the OCI image config for secrets baked into
  `ENV` instructions (e.g. `ENV SECRET_KEY=...` in a Containerfile). These survive layer
  squashing and are visible to anyone who pulls the image.

Both are additive to the existing vuln scan and use the same `exit-code` setting (report-only
on PRs, gating on push). Secret findings appear as SARIF annotations in the GitHub Security tab
alongside CVEs.

**Important:** secret scanning is best-effort — Trivy detects high-entropy strings and known
secret patterns, but cannot catch all credential types. The primary defence against secrets
in images remains not putting them there (`detect-private-key` pre-commit hook +
`secrets:` block in Containerfiles replaced by runtime injection).
