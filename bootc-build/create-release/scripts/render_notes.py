#!/usr/bin/env python3
# GITHUB_RELEASE_BODY_LIMIT — GitHub enforces a hard 125 000-character cap on
# release bodies (HTTP 422 "body is too long").  render_notes.py stays well
# under that by checking the assembled text against --max-chars (default
# 120 000).  When the limit would be exceeded the full notes are written to a
# separate overflow file (default release-notes-full.md) so they can be
# attached as a release asset, and a trimmed body is written to --output.
"""
render_notes.py — Generate release notes markdown with full SBOM display
and step-by-step supply chain verification instructions using CNCF tools.

Usage:
    python3 render_notes.py \\
        --versions       versions.json \\
        --sbom           current.spdx.json \\
        --tag            2026-05-14-abc1234 \\
        --title          "Bluefin Stable 2026-05-14" \\
        --image          ghcr.io/projectbluefin/bluefin \\
        --digest         sha256:abc123... \\
        --repo           projectbluefin/bluefin \\
        --project-name   "Bluefin" \\
        --cert-regexp    "^https://github\\.com/projectbluefin/(bluefin|actions)/.github/workflows/" \\
        --docs-url       "https://docs.projectbluefin.io/changelogs" \\
        --sbom-filename  bluefin.spdx.json \\
        --output         release-notes.md

The generated release notes include:
  1. Release card image embed
  2. Key component versions (notable packages)
  3. Full SPDX package inventory in a collapsible <details> block
  4. Supply chain verification section using CNCF / OpenSSF tools:
       - cosign  (Sigstore — image signature + attestations)
       - oras    (CNCF graduated — SBOM OCI referrer)
       - slsa-verifier (OpenSSF — SLSA Build L2 provenance)
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    sep = " | ".join("---" for _ in headers)
    head = " | ".join(headers)
    body = "\n".join(" | ".join(r) for r in rows)
    return f"| {head} |\n| {sep} |\n" + "\n".join(f"| {r} |" for r in
           [" | ".join(row) for row in rows])


# ── SBOM inventory ────────────────────────────────────────────────────────────

def _load_full_inventory(sbom_path: str) -> list[dict]:
    """Return all named packages from the SPDX-JSON sorted alphabetically."""
    with open(sbom_path, encoding="utf-8") as f:
        sbom = json.load(f)
    seen: dict[str, str] = {}
    for p in sbom.get("packages", []):
        name = p.get("name", "").strip()
        ver  = p.get("versionInfo", "").strip()
        if not name:
            continue
        # Keep first occurrence; prefer non-empty version
        if name not in seen or (not seen[name] and ver):
            seen[name] = ver
    return [{"name": k, "version": v} for k, v in sorted(seen.items())]


# ── Section builders ──────────────────────────────────────────────────────────

def _section_card(tag: str, repo: str) -> str:
    url = f"https://github.com/{repo}/releases/download/{tag}/release-card.png"
    return f"![Release card]({url})\n"


def _section_notable(notable: list[dict]) -> str:
    if not notable:
        return ""
    rows = []
    for p in notable:
        change = ""
        if p.get("changed") and p.get("prev"):
            change = f"`{p['prev']}` → `{p['version']}`"
        rows.append(
            f"| **{p['name']}** | `{p['version']}` | {change} |"
        )
    return (
        "## Key components\n\n"
        "| Component | Version | Change |\n"
        "|---|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


def _section_diff_summary(diff: dict, has_prev: bool, total: int) -> str:
    if not has_prev:
        return (
            f"> **{total} packages** in this image. "
            "No previous release baseline — full inventory below.\n"
        )
    parts = []
    if diff["changed_count"]:
        parts.append(f"**{diff['changed_count']} updated**")
    if diff["added_count"]:
        parts.append(f"**{diff['added_count']} added**")
    if diff["removed_count"]:
        parts.append(f"**{diff['removed_count']} removed**")
    summary = ", ".join(parts) if parts else "no package changes"
    return (
        f"> {summary} since the previous release. "
        f"**{total} packages** total — full inventory below.\n"
    )


def _section_full_inventory(inventory: list[dict], total: int) -> str:
    rows = "\n".join(
        f"| `{p['name']}` | `{p['version']}` |" for p in inventory
    )
    return (
        f"<details>\n"
        f"<summary>📦 Full SPDX package inventory — {total} packages</summary>\n\n"
        f"| Package | Version |\n"
        f"|---|---|\n"
        f"{rows}\n\n"
        f"</details>\n"
    )


def _section_diff_details(diff: dict, has_prev: bool) -> str:
    if not has_prev:
        return ""
    blocks: list[str] = []

    if diff["changed"]:
        rows = "\n".join(
            f"| `{c['name']}` | `{c['prev']}` | `{c['curr']}` |"
            for c in diff["changed"]
        )
        blocks.append(
            f"<details>\n"
            f"<summary>↑ {diff['changed_count']} updated packages</summary>\n\n"
            f"| Package | From | To |\n"
            f"|---|---|---|\n"
            f"{rows}\n\n"
            f"</details>"
        )

    if diff["added"]:
        rows = "\n".join(
            f"| `{a['name']}` | `{a['version']}` |"
            for a in diff["added"]
        )
        blocks.append(
            f"<details>\n"
            f"<summary>+ {diff['added_count']} added packages</summary>\n\n"
            f"| Package | Version |\n"
            f"|---|---|\n"
            f"{rows}\n\n"
            f"</details>"
        )

    if diff["removed"]:
        rows = "\n".join(
            f"| `{r['name']}` | `{r['version']}` |"
            for r in diff["removed"]
        )
        blocks.append(
            f"<details>\n"
            f"<summary>− {diff['removed_count']} removed packages</summary>\n\n"
            f"| Package | Last version |\n"
            f"|---|---|\n"
            f"{rows}\n\n"
            f"</details>"
        )

    if not blocks:
        return ""
    return "## Package changes\n\n" + "\n\n".join(blocks) + "\n"


def _section_supply_chain(
    *,
    image: str,
    digest: str,
    repo: str,
    tag: str,
    cert_regexp: str,
    sbom_filename: str,
    docs_url: str,
) -> str:
    """
    Supply chain verification section using CNCF / OpenSSF tools:
      - cosign   (Sigstore, CNCF ecosystem) — image signature & attestations
      - oras     (CNCF graduated)           — SBOM OCI referrer
      - slsa-verifier (OpenSSF)             — SLSA Build L2 provenance

    Install all three via Homebrew:
        brew install cosign oras slsa-verifier
    Or see:
        https://github.com/sigstore/cosign
        https://oras.land
        https://github.com/slsa-framework/slsa-verifier
    """
    image_at_digest = f"{image}@{digest}"

    return f"""\
## Supply chain

This image is signed, attested, and ships a full SPDX-JSON SBOM.
Every artifact below is verifiable without trusting this release page.

**Tools required** — install via Homebrew or see links in each section:

```bash
brew install cosign oras slsa-verifier
```

---

### 1 — Verify the image signature

[cosign](https://github.com/sigstore/cosign) (Sigstore) verifies the keyless
OIDC signature created by GitHub Actions at build time.

```bash
cosign verify \\
  --certificate-identity-regexp '{cert_regexp}' \\
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \\
  {image_at_digest}
```

A valid response lists the certificate subject and OIDC issuer. Any tampered
image will produce a verification error.

---

### 2 — Fetch and inspect the SBOM

The SBOM ([SPDX 2.3 JSON](https://spdx.dev/)) is attached to the image as an
[OCI referrer](https://oras.land) using
[ORAS](https://github.com/oras-project/oras) (CNCF graduated project).

```bash
# Discover the attached SBOM referrer
oras discover \\
  --artifact-type application/vnd.spdx+json \\
  {image_at_digest}

# Pull the SBOM to disk (replace SBOM_DIGEST with the digest from above)
oras pull \\
  --artifact-type application/vnd.spdx+json \\
  {image}@<SBOM_DIGEST>
```

The SBOM is also attached to this release as
[`{sbom_filename}`](https://github.com/{repo}/releases/download/{tag}/{sbom_filename}).

---

### 3 — Verify the SBOM attestation

The SBOM is also stored as a signed
[GitHub SBOM attestation](https://docs.github.com/en/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds)
in the Sigstore transparency log.

```bash
cosign verify-attestation \\
  --type https://spdx.dev/Document \\
  --certificate-identity-regexp '{cert_regexp}' \\
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \\
  {image_at_digest} \\
  | jq -r '.payload | @base64d | fromjson | .predicate.name'
```

---

### 4 — Verify SLSA Build L2 provenance

[slsa-verifier](https://github.com/slsa-framework/slsa-verifier) (OpenSSF)
checks that this image was built by the expected workflow on the expected
source repository — not on a developer's laptop or a forked CI runner.

```bash
slsa-verifier verify-image \\
  {image_at_digest} \\
  --source-uri 'github.com/{repo}' \\
  --source-versioned-tag '{tag}'
```

You can also inspect the raw provenance:

```bash
cosign verify-attestation \\
  --type slsaprovenance1 \\
  --certificate-identity-regexp '{cert_regexp}' \\
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \\
  {image_at_digest} \\
  | jq -r '.payload | @base64d | fromjson | .predicate'
```

---

Full changelog and verification guide → {docs_url}
"""


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions",      required=True, help="versions.json from sbom_diff.py")
    ap.add_argument("--sbom",          required=True, help="Current SPDX-JSON SBOM path")
    ap.add_argument("--tag",           required=True)
    ap.add_argument("--title",         required=True)
    ap.add_argument("--image",         required=True,
                    help="Full image ref without tag, e.g. ghcr.io/projectbluefin/bluefin")
    ap.add_argument("--digest",        required=True, help="sha256:...")
    ap.add_argument("--repo",          required=True, help="org/repo")
    ap.add_argument("--project-name",  default="Bluefin")
    ap.add_argument("--cert-regexp",   required=True,
                    help="cosign --certificate-identity-regexp value")
    ap.add_argument("--docs-url",      default="https://docs.projectbluefin.io/changelogs")
    ap.add_argument("--sbom-filename", default="",
                    help="Filename of SBOM asset attached to the release (e.g. bluefin.spdx.json)")
    ap.add_argument("--output",        default="release-notes.md")
    ap.add_argument(
        "--max-chars",
        type=int,
        default=120_000,
        help="Hard cap on the release body (default 120 000; GitHub limit is 125 000)",
    )
    ap.add_argument(
        "--overflow-file",
        default="release-notes-full.md",
        help="Path to write the *full* notes when truncation occurs "
             "(attach this file as a release asset)",
    )
    args = ap.parse_args()

    for path, label in [(args.versions, "--versions"), (args.sbom, "--sbom")]:
        if not os.path.isfile(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    with open(args.versions, encoding="utf-8") as f:
        versions = json.load(f)

    sbom_filename = args.sbom_filename or os.path.basename(args.sbom)

    inventory = _load_full_inventory(args.sbom)
    total     = versions.get("total_packages", len(inventory))

    sections = [
        _section_card(args.tag, args.repo),
        "",
        _section_diff_summary(versions["diff"], versions["has_prev"], total),
        "",
        _section_notable(versions["notable"]),
        "",
        _section_full_inventory(inventory, total),
        "",
        _section_diff_details(versions["diff"], versions["has_prev"]),
        "",
        _section_supply_chain(
            image=args.image,
            digest=args.digest,
            repo=args.repo,
            tag=args.tag,
            cert_regexp=args.cert_regexp,
            sbom_filename=sbom_filename,
            docs_url=args.docs_url,
        ),
    ]

    notes = "\n".join(sections)

    # ── Guard: GitHub enforces a 125 000-char limit on release bodies ────────
    if len(notes) > args.max_chars:
        # Persist the full notes as a separate asset so nothing is lost.
        with open(args.overflow_file, "w", encoding="utf-8") as f:
            f.write(notes)
        print(
            f"::warning::Release notes are {len(notes):,} chars "
            f"(limit {args.max_chars:,}). Full notes written to "
            f"'{args.overflow_file}' — it will be attached as a release asset.",
            file=sys.stderr,
        )

        # Build a compact body: drop the full inventory + diff details blocks;
        # replace them with a pointer to the overflow asset.
        asset_ref = os.path.basename(args.overflow_file)
        overflow_note = (
            f"_The full package inventory and diff details exceed GitHub's "
            f"release-body limit.  "
            f"They are attached as [`{asset_ref}`]({asset_ref})._\n"
        )
        compact_sections = [
            _section_card(args.tag, args.repo),
            "",
            _section_diff_summary(versions["diff"], versions["has_prev"], total),
            "",
            _section_notable(versions["notable"]),
            "",
            overflow_note,
            "",
            _section_supply_chain(
                image=args.image,
                digest=args.digest,
                repo=args.repo,
                tag=args.tag,
                cert_regexp=args.cert_regexp,
                sbom_filename=sbom_filename,
                docs_url=args.docs_url,
            ),
        ]
        notes = "\n".join(compact_sections)

        # Absolute last resort: hard-truncate if even the compact body is over.
        if len(notes) > args.max_chars:
            notes = notes[: args.max_chars - 12] + "\n\n…*(truncated)*"
            print(
                "::warning::Compact release notes still exceeded the limit — "
                "hard-truncated.",
                file=sys.stderr,
            )

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(notes)
    print(f"Release notes written: {args.output} ({len(notes):,} chars)")


if __name__ == "__main__":
    main()
