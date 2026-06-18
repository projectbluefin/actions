---
name: determinism
description: Non-deterministic surfaces in the projectbluefin factory — classification, mitigations, and open investigations. Use when auditing build reproducibility, verifying SHA pins are accurate, or investigating why two builds from the same source produce different artifacts.
metadata:
  type: reference
---

# Determinism in the projectbluefin Actions Factory

## Philosophy

Determinism in the factory means: **same inputs → same outputs**. A deterministic build system ensures that rebuilding the same image from the same source code and pinned dependencies produces byte-for-byte identical artifacts. This enables reproducible testing, verifiable releases, and confidence that a known-good build can be replicated.

Non-determinism falls into three categories:
1. **Acceptable drift** — sources outside our control; document and monitor
2. **Already pinned** — surface is locked; verify and maintain
3. **Under investigation** — requires fixes or trade-off decisions

---

## Gold Standards (Model These Patterns)

### 1. SHA-locking in weekly testing promotion (`bluefin/.github/workflows/weekly-testing-promotion.yml`)

**Pattern:** Before promoting a testing build to stable, lock the main branch HEAD SHA:

```bash
SHA=$(gh api repos/${{ github.repository }}/git/ref/heads/main --jq '.object.sha')
```

Then verify that e2e tests passed **on that exact SHA** before proceeding. This ensures:
- No hidden commits between decision point and build
- Reproducible promotion logic
- Auditable trail (SHA is part of workflow state)

**Why it works:** Git SHAs are immutable content hashes. Once locked, the repository state is deterministic.

### 2. E2E gate locks to source_branch HEAD SHA — not a hardcoded ref

**Pattern:** The promote-squash E2E gate queries the *branch* that E2E workflows run against
(e.g. `testing`), resolves its current HEAD SHA at gate-time, and verifies that E2E passed
**on that exact SHA**:

```bash
SHA=$(gh api repos/$REPO/git/ref/heads/$E2E_HEAD_BRANCH --jq '.object.sha')
```

Never use a hardcoded branch name (`main`) or the caller's `github.ref` as the gate target.
Either can match a commit that hasn't had E2E run yet, allowing untested code through.

**Why it matters:** Git branch refs are mutable. The same branch name resolves to a different
commit between the E2E run and the gate check if any push lands in between. Locking to the
resolved SHA at gate-time closes this race.

---

### 3. Pinned build engine in dakota (`dakota/.github/actions/check-bst2-pin/`)

**Pattern:** BuildStream 2 (the compilation engine) is pinned to an exact container image SHA in both the Justfile and CI workflow:

```bash
just_sha="$(grep -oE 'bst2:[a-f0-9]{40}' Justfile)"
track_sha="$(grep -oE 'bst2:[a-f0-9]{40}' .github/workflows/track-bst-sources.yml)"
```

A CI check enforces they match. This ensures:
- Compiler version cannot drift between local and CI builds
- BST2 updates are deliberate and synchronized
- Reproducible builds across all developers and CI runners

**Why it works:** Container image SHAs are immutable. Pinning the builder guarantees identical compilation behavior.

---

## Acceptable Drift (Document, Do Not Eliminate)

### 1. Upstream RPM versions

**Surface:** Fedora updates base packages daily. Builds on different dates pull different RPM versions.

**Why acceptable:**
- Pinning every RPM creates maintenance burden
- Security updates are critical and frequent
- `dnf cache` action mitigates by reusing cached layers
- Latest-stable is the right policy for desktop OS (Bluefin)

**Mitigation:**
- DNF cache in reusable workflow reduces re-download of unchanged packages
- Document expected drift in release notes
- Run weekly e2e testing to catch breakage early

**Status:** ✅ Intentional, monitored via weekly CI

### 2. Cron schedule timing and runner OS freshness

**Surface:** GitHub Actions runners are updated weekly; `cron: '0 6 * * 2'` may run on different patch levels of Ubuntu 24.04.

**Why acceptable:**
- Runner OS updates are security-critical
- Patch-level differences in Ubuntu are minimal (same kernel ABI)
- Workflow runs at consistent UTC time, not wall-clock time

**Mitigation:**
- Document runner image version in build logs
- Use stable runner labels (`ubuntu-24.04`, `ubuntu-24.04-arm`)
- Monitor for runner-specific failures in e2e tests

**Status:** ✅ Acceptable, runner selection is deliberate

### 3. Container storage initialization order

**Surface:** BTRFS loopback mount (`setup-runner` input `storage-backend: btrfs`) initializes before each build. Mount options and loopback device numbering vary between runs.

**Why acceptable:**
- BTRFS initialization is stable and repeatable on the same runner
- The compressed filesystem is transparent to the build
- Layer ordering inside a built image is deterministic (controlled by build tool)

**Mitigation:**
- Use `compress-force=zstd:2` to ensure consistent compression
- Verify in smoke tests that layer digests match between builds
- Monitor for storage-related flakes in CI

**Status:** ✅ Acceptable, reproducible within same runner pool

---

## Already Pinned (Verify and Maintain)

### 1. Third-party action SHAs in all composite actions

**Pattern:** Every `uses:` reference in `bootc-build/*/action.yml` and `.github/workflows/reusable-build.yml` must be pinned to a full commit SHA with a version comment. No floating tags (`@main`, `@v3`, `@latest`).

**How to verify the repo is clean:**
```bash
# Find any floating tags — should return nothing
grep -r 'uses:' bootc-build/ .github/workflows/ \
  | grep -v '@[0-9a-f]\{40\}'
```

**How to verify a SHA comment is accurate (not a pre-release branch tip):**
```bash
# Check that the comment tag exists as a real release, not just a branch ref
gh release view v6.0.3 --repo actions/checkout --json tagName
# If no release exists, use: # no-release, <landmark> (YYYY-MM)
```

**Version comment rules:**
- Use the **exact** release tag: `# v6.0.3` not `# v6`
- For repos with no releases/tags: `# no-release, Merge PR #N (YYYY-MM)`
- Renovate bumps SHAs in consuming repos — the canonical pins live here

**Chunkah container SHA:**
- Version and digest both pinned in `chunka/action.yml` (`CHUNKAH_VERSION` + `CHUNKAH_SHA`)
- Bump both together when upgrading — they derive the image ref and the Containerfile.splitter URL

**Dakota BST2 pin:**
- Enforced by `dakota/.github/actions/check-bst2-pin/` consistency check
- Pinned in both Justfile and workflow — CI blocks drift

---

## Open Investigations

### 1. Chunkah reproducibility

**Question:** Does chunkah produce identical rechunked images from identical inputs?

**Context:**
- Chunkah is an external tool (coreos/chunkah, container-based)
- Layer ordering is stable
- OCI layer digests are checked (line 55 in chunka/action.yml: `ostree.components` annotations)
- Test suite: rechunk step in reusable workflow verifies metadata preserved (lines 418–432)

**Current mitigation:**
- Full SHA pin on container image
- Verify annotations preserved in reusable workflow
- Layer digests logged for debugging

**Next steps:**
- Compare digests of rechunked images across two identical builds (same source, same runner pool)
- If drift detected, file issue on coreos/chunkah with reproducible case

**Status:** 🟡 Assumption of determinism, not yet verified empirically

### 2. SOURCE_DATE_EPOCH in Containerfile builds

**Question:** Are Containerfile builds using SOURCE_DATE_EPOCH to pin timestamps?

**Analysis:**
- Neither bluefin nor dakota sets `SOURCE_DATE_EPOCH` in Containerfiles or Justfiles
- Podman respects it if set in the runner environment, but it is not set
- Timestamps (e.g., file mtimes inside built images) may vary between runs

**Impact:**
- Minimal for bootc images (timestamps in /etc are not part of runtime state)
- Relevant for SBOM metadata (generation timestamp is recorded)
- Could affect reproducible builds if using timestamps for verification

**Current mitigation:**
- SBOM generation captures workflow run timestamp separately
- Attestations include build metadata (run ID, timestamp)

**Next steps:**
1. Verify that OSTree commit hashes are deterministic (not timestamp-dependent)
2. If needed, set `SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)` in build steps
3. Pin in consuming repos if cross-repo reproducibility is required

**Status:** 🟡 Not yet set; investigate if needed for reproducibility requirement

### 3. AT-SPI test flakes in e2e testing

**Question:** Why do Accessibility (AT-SPI) tests occasionally fail in e2e runs?

**Context:**
- post-testing-e2e runs smoke tests before weekly promotion
- AT-SPI dbus initialization can be timing-sensitive
- Runs on shared GitHub Actions runners with variable load

**Current mitigation:**
- Rerun button available if flake occurs
- Monitoring in project board for test stability

**Next steps:**
- Add AT-SPI service availability check to e2e harness
- Consider longer timeout for accessibility tests
- Log detailed dbus trace on failure

**Status:** 🟡 Known intermittent; needs CI harness improvement

---

## Audit Schedule and Ownership

| Item | Cadence | Owner |
|------|---------|-------|
| Third-party action SHA updates | Monthly (via Renovate PR review) | @castrojo |
| Chunkah reproducibility test | Quarterly | Agent-run (reproducibility CI) |
| SOURCE_DATE_EPOCH decision | Next design review | Architecture review |
| AT-SPI test flake analysis | As-needed (PR blocking) | Whoever hits it in CI |

---

## How to Use This File

- **Floating tag found in a new workflow?** → Flag under "Critical: must fix" and add to `actionlint` check
- **Need to update a pinned action?** → Search this file for the action name, verify new SHA, update with version comment
- **New non-deterministic surface discovered?** → Add to the appropriate section and create a tracking issue
- **Investigation resolved?** → Move section to "Already pinned" with mitigation summary

---

## Related Reading

- [`docs/skills/composite-actions.md`](composite-actions.md) — SHA pinning conventions and adding new actions
- [`docs/skills/consumer-guide.md`](consumer-guide.md) — How consuming repos stay in sync with factory updates
- `bluefin/.github/workflows/weekly-testing-promotion.yml` — Gold standard for SHA-locking
- `dakota/.github/actions/check-bst2-pin/` — Gold standard for builder pinning
