"""Drift gate for the Sigstore trust policy and tag→digest resolution clusters.

Two contracts in this repository are restated at many call sites instead of
living in one place, and self-reference (`uses: projectbluefin/actions/...` or
`uses: ./...`) is deliberately banned by `scripts/check-self-repository-references.py`
because it resolves against the *caller's* workspace. Extraction is therefore not
available, so the copies are structural — what is missing is a gate that keeps
them honest:

1. **Sigstore trust policy** — every `cosign verify` / `cosign verify-attestation`
   invocation must pin the same OIDC issuer and must take the certificate identity
   from a variable, never a baked-in literal. Today this is stated at 7 sites in
   5 files (two shipped workflows, one composite action, one extracted script, and
   three user-facing instruction blocks emitted by `render_notes.py`), and only the
   `reusable-release-gate.yml` pair is covered by `test_release_gate_single_source.py`.

2. **Tag→digest resolution** — `skopeo inspect --format '{{.Digest}}'` is the one
   sanctioned way to turn a mutable tag into an immutable digest before signing,
   gating or promoting. It is restated at 4 sites.

These tests do not deduplicate anything. They make every copy declared: adding a
new `cosign verify` call site or a new digest-resolution site fails until it is
listed here, which forces the author to compare it against the existing copies.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SEARCH_ROOTS = (".github", "bootc-build", "actions", "scripts")
SEARCH_SUFFIXES = {".yml", ".yaml", ".sh", ".py"}

TRUSTED_OIDC_ISSUER = "https://token.actions.githubusercontent.com"

# Every file that invokes `cosign verify` / `cosign verify-attestation`, or that
# emits such an invocation for a user to run. Adding a call site means adding it
# here, on purpose, after checking it agrees with the copies below.
DECLARED_COSIGN_VERIFY_SITES = {
    ".github/workflows/reusable-execute-release.yml",
    ".github/workflows/reusable-release-gate.yml",
    "bootc-build/create-release/scripts/render_notes.py",
    "bootc-build/sign-and-publish/action.yml",
    "scripts/verify_signatures.sh",
}

# Every file that resolves a mutable tag to an immutable digest with skopeo.
DECLARED_DIGEST_RESOLUTION_SITES = {
    ".github/workflows/reusable-execute-release.yml",
    ".github/workflows/reusable-release-gate.yml",
    ".github/workflows/reusable-release.yml",
    "scripts/resolve_digests.sh",
}

COSIGN_VERIFY = re.compile(r"cosign\s+verify(-attestation)?\s")
DIGEST_RESOLUTION = re.compile(r"skopeo\s+inspect\s+--format\s+'\{\{\.Digest\}\}'")
OIDC_ISSUER_FLAG = re.compile(r"--certificate-oidc-issuer[=\s]+['\"]?([^'\"\s\\]+)")
IDENTITY_FLAG = re.compile(r"--certificate-identity-regexp[=\s]+(\S+)")

# A pinned identity literal, e.g. 'https://github.com/org/repo/.github/...'.
# Identities must arrive through an env var, a workflow input or a format
# placeholder so a single caller-supplied value drives every verification.
IDENTITY_INDIRECTION = re.compile(
    r"(\$[A-Za-z0-9_]|\$\{[A-Za-z0-9_]+|\$\{\{|\{[a-z0-9_]+\})"
)


def _source_files() -> list[Path]:
    return sorted(
        path
        for root in SEARCH_ROOTS
        for path in (REPO_ROOT / root).rglob("*")
        if path.is_file()
        and path.suffix in SEARCH_SUFFIXES
        and not any(part.endswith(("-work", "-worktree")) for part in path.parts)
    )


def _strip_comments(text: str) -> str:
    """Drop whole-line comments and argparse help strings.

    Both mention the flags below without being verification call sites.
    """
    return "\n".join(
        line
        for line in text.splitlines()
        if not line.lstrip().startswith("#") and "help=" not in line
    )


def _sites(pattern: re.Pattern[str]) -> set[str]:
    found = set()
    for path in _source_files():
        if pattern.search(_strip_comments(path.read_text(encoding="utf-8"))):
            found.add(path.relative_to(REPO_ROOT).as_posix())
    return found


def test_every_cosign_verify_site_is_declared():
    """A new signature-verification call site must be declared, not smuggled in."""
    assert _sites(COSIGN_VERIFY) == DECLARED_COSIGN_VERIFY_SITES, (
        "the set of cosign verification call sites changed. Compare the new copy "
        "against the existing ones (issuer, identity source, failure handling) and "
        "then update DECLARED_COSIGN_VERIFY_SITES."
    )


def test_every_digest_resolution_site_is_declared():
    """A new tag→digest resolution site must be declared, not smuggled in."""
    assert _sites(DIGEST_RESOLUTION) == DECLARED_DIGEST_RESOLUTION_SITES, (
        "the set of tag→digest resolution sites changed. Compare the new copy "
        "against the existing ones (variant grammar, failure handling) and then "
        "update DECLARED_DIGEST_RESOLUTION_SITES."
    )


def test_all_sites_pin_the_same_oidc_issuer():
    """One issuer, stated identically everywhere — including in emitted docs."""
    seen = 0
    for relpath in sorted(DECLARED_COSIGN_VERIFY_SITES):
        text = _strip_comments((REPO_ROOT / relpath).read_text(encoding="utf-8"))
        issuers = OIDC_ISSUER_FLAG.findall(text)
        assert issuers, f"{relpath} verifies signatures without pinning an OIDC issuer"
        for issuer in issuers:
            assert issuer == TRUSTED_OIDC_ISSUER, (
                f"{relpath} pins OIDC issuer {issuer!r}; every verification site "
                f"must pin {TRUSTED_OIDC_ISSUER!r}"
            )
        seen += len(issuers)
    assert seen >= len(DECLARED_COSIGN_VERIFY_SITES)


def test_certificate_identity_is_never_hardcoded():
    """The signing identity is caller policy: it must never be baked into a copy."""
    for relpath in sorted(DECLARED_COSIGN_VERIFY_SITES):
        text = _strip_comments((REPO_ROOT / relpath).read_text(encoding="utf-8"))
        identities = IDENTITY_FLAG.findall(text)
        assert identities, (
            f"{relpath} verifies signatures without --certificate-identity-regexp, "
            "so it accepts a signature from any identity the issuer vouches for"
        )
        for identity in identities:
            assert IDENTITY_INDIRECTION.search(identity), (
                f"{relpath} hardcodes the certificate identity {identity!r}; pass it "
                "through an env var, workflow input or template placeholder so one "
                "caller-supplied policy drives every verification"
            )


def test_declared_sites_exist():
    """A declaration for a deleted file is stale and hides a shrinking cluster."""
    for relpath in DECLARED_COSIGN_VERIFY_SITES | DECLARED_DIGEST_RESOLUTION_SITES:
        assert (REPO_ROOT / relpath).is_file(), f"declared site {relpath} no longer exists"
