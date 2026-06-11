#!/usr/bin/env python3
"""
render_pr_body.py — Generate the promotion PR body (testing → stable).

Called by both reusable-promote-squash.yml (squash/git workflow) and
reusable-promote.yml (digest workflow).  The body contains HTML marker
comments around the gate section so the gate job can do a targeted
replacement without touching the rest of the body.

Usage (squash workflow — has git log, no digests yet):
    python3 render_pr_body.py \\
        --project-name        "Bluefin" \\
        --primary-image       "bluefin" \\
        --variants-json       '[{"image":"bluefin"},{"image":"bluefin-nvidia"}]' \\
        --repo                "projectbluefin/bluefin" \\
        --run-url             "https://github.com/.../runs/123" \\
        --date                "2026-06-11" \\
        --days-since-stable   12 \\
        --last-release-tag    "stable-20260530-abc1234" \\
        --last-release-url    "https://github.com/.../releases/tag/stable-20260530-abc1234" \\
        --commit-count        54 \\
        --commits-json        '[{"sha":"abc1234def5","subject":"feat: stuff"}]' \\
        --compare-url         "https://github.com/.../compare/main...testing" \\
        --output              /tmp/pr-body.md

Usage (digest workflow — variants include resolved digests, no git log):
    python3 render_pr_body.py \\
        --project-name        "Dakota" \\
        --primary-image       "dakota" \\
        --variants-json       '[{"image":"dakota","digest":"sha256:abc..."}]' \\
        --repo                "projectbluefin/dakota" \\
        --run-url             "https://github.com/.../runs/456" \\
        --date                "2026-06-11" \\
        --days-since-stable   5 \\
        --last-release-tag    "stable-20260606-def5678" \\
        --last-release-url    "https://github.com/.../releases/tag/stable-20260606-def5678" \\
        --output              /tmp/pr-body.md

The gate section is bounded by HTML markers for targeted replacement:
    <!-- gate-section-start -->
    ...checklist rows...
    <!-- gate-section-end -->
"""
import argparse
import json
import sys
from datetime import datetime, timezone

GATE_START = "<!-- gate-section-start -->"
GATE_END   = "<!-- gate-section-end -->"


# ── Section builders ──────────────────────────────────────────────────────────

def _section_header(
    project_name: str,
    date: str,
    run_url: str,
    *,
    days_ago: int | None,
    last_tag: str | None,
    last_release_url: str | None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if days_ago is not None and last_tag and last_release_url:
        noun = "day" if days_ago == 1 else "days"
        days_line = (
            f"> **{days_ago} {noun} since the last stable release**"
            f" · [{last_tag} ↗]({last_release_url})  \n"
        )
    else:
        days_line = ""

    return (
        f"## 🦕 {project_name} testing → stable · {date}\n\n"
        f"{days_line}"
        f"> Auto-maintained by `promote-testing-to-main.yml` · "
        f"Updated `{now}` · [Run ↗]({run_url})\n"
    )


def _section_gate_placeholder() -> str:
    rows = "\n".join(
        f"| {name} | ⏳ checking… | — |"
        for name in ("Digest resolution", "Cosign signatures", "E2E")
    )
    return (
        f"{GATE_START}\n"
        "### Release checklist\n\n"
        "| Check | Status | Details |\n"
        "|---|---|---|\n"
        f"{rows}\n"
        f"{GATE_END}\n"
    )


def _section_variants(variants: list[dict], source_tag: str) -> str:
    has_digests = any("digest" in v for v in variants)

    if has_digests:
        header = "| Variant | Tag | Digest |\n|---|---|---|\n"
        rows = []
        for v in variants:
            image  = v["image"]
            digest = v.get("digest", "")
            if digest.startswith("sha256:"):
                short = f"`sha256:{digest[7:23]}`"
            elif digest:
                short = f"`{digest[:16]}`"
            else:
                short = "—"
            rows.append(f"| `{image}` | `:{source_tag}` | {short} |")
    else:
        header = "| Variant | Tag |\n|---|---|\n"
        rows   = [f"| `{v['image']}` | `:{source_tag}` |" for v in variants]

    return "### Variants being promoted\n\n" + header + "\n".join(rows) + "\n"


def _section_commits(
    count: int,
    commits: list[dict],
    compare_url: str | None,
) -> str:
    if count == 0 and not commits:
        return ""

    compare_link = f" · [Compare main…testing ↗]({compare_url})" if compare_url else ""
    noun = "commit" if count == 1 else "commits"
    intro = f"**{count} {noun}** ahead of stable{compare_link}\n"

    if not commits:
        return "### Changes since last stable\n\n" + intro

    rows = "\n".join(
        # Escape pipe characters that would break the markdown table
        f"| `{c['sha'][:7]}` | {c['subject'].replace('|', chr(92) + '|')} |"
        for c in commits
    )
    details = (
        "<details>\n"
        f"<summary>Recent commits (showing last {len(commits)})</summary>\n\n"
        "| SHA | Subject |\n"
        "|---|---|\n"
        f"{rows}\n\n"
        "</details>"
    )
    return "### Changes since last stable\n\n" + intro + "\n" + details + "\n"


def _section_footer() -> str:
    return (
        "---\n\n"
        "_✅ Merge to publish the stable release once the checklist above is green._\n"
    )


# ── Title builder ─────────────────────────────────────────────────────────────

def build_title(primary_image: str, date: str) -> str:
    """
    Consistent promotion PR title across all image repos:
        ci(promote): <image> testing → stable YYYY-MM-DD
    """
    return f"ci(promote): {primary_image} testing → stable {date}"


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Render promotion PR body (testing → stable)")
    ap.add_argument("--project-name",       required=True,
                    help="Display name, e.g. 'Bluefin LTS'")
    ap.add_argument("--primary-image",      required=True,
                    help="Primary image slug for title, e.g. 'bluefin-lts'")
    ap.add_argument("--variants-json",      required=True,
                    help="JSON array of variant objects: [{\"image\": str, \"digest\"?: str}]")
    ap.add_argument("--repo",               required=True, help="owner/repo")
    ap.add_argument("--run-url",            required=True, help="GitHub Actions run URL")
    ap.add_argument("--date",               required=True, help="Promotion date YYYY-MM-DD")
    ap.add_argument("--days-since-stable",  type=int, default=None,
                    help="Days since last stable release (omit if no prior release)")
    ap.add_argument("--last-release-tag",   default="",
                    help="Tag of last stable release")
    ap.add_argument("--last-release-url",   default="",
                    help="HTML URL of last stable release")
    ap.add_argument("--commit-count",       type=int, default=0,
                    help="Number of commits testing is ahead of main/stable")
    ap.add_argument("--commits-json",       default="[]",
                    help="JSON array of {sha, subject} objects (recent commits)")
    ap.add_argument("--compare-url",        default="",
                    help="GitHub compare URL: .../compare/main...testing")
    ap.add_argument("--source-tag",         default="testing",
                    help="Source tag being promoted (default: testing)")
    ap.add_argument("--output",             default="pr-body.md")
    args = ap.parse_args()

    variants = json.loads(args.variants_json)
    commits  = json.loads(args.commits_json)

    sections = [
        _section_header(
            args.project_name, args.date, args.run_url,
            days_ago=args.days_since_stable,
            last_tag=args.last_release_tag or None,
            last_release_url=args.last_release_url or None,
        ),
        "",
        _section_gate_placeholder(),
        "",
        _section_variants(variants, args.source_tag),
        "",
        _section_commits(args.commit_count, commits, args.compare_url or None),
        "",
        _section_footer(),
    ]

    body = "\n".join(sections)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(body)

    title = build_title(args.primary_image, args.date)
    print(f"PR body written: {args.output} ({len(body):,} chars)")
    print(f"PR title: {title}")


if __name__ == "__main__":
    main()
