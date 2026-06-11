# Promotion PR Body & Consistent Titles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the thin, inconsistent promotion PR bodies and titles with Design C: a consistent 🦕-branded title, a "X days since last stable release" subtitle, gate checks inline in the body (updated live by the gate job), and a collapsible commit log — running on every push to the testing branch.

**Architecture:** A new `scripts/render_pr_body.py` generates the PR body with HTML marker comments around the gate section. The `promote` job writes the body with ⏳ placeholders; the `gate` job replaces only the marker-bounded gate section with live results. Both jobs update the PR body via `gh pr edit --body-file`. The "days since last stable" is fetched with `gh release list` in the promote job.

**Tech Stack:** Python 3 stdlib, `gh` CLI, `skopeo`, GitHub Actions YAML, pytest.

---

## Approved design (Design C)

Gist: https://gist.github.com/castrojo/99f4c7e7c433c4549b262929ba25d365

```
Title: ci(promote): bluefin testing → stable 2026-06-11
```

```markdown
## 🦕 Bluefin testing → stable · 2026-06-11

> **12 days since the last stable release** · [stable-20260530-abc1234 ↗](release-url)
> Auto-maintained by `promote-testing-to-main.yml` · Updated `2026-06-11T18:42:00Z` · [Run ↗](run-url)

<!-- gate-section-start -->
### Release checklist

| Check | Status | Details |
|---|---|---|
| Digest resolution | ⏳ checking… | — |
| Cosign signatures | ⏳ checking… | — |
| E2E (smoke) | ⏳ checking… | — |
<!-- gate-section-end -->

### Variants being promoted

| Variant | Tag | Digest |
|---|---|---|
| `bluefin` | `:testing` | `sha256:a1b2c3d4e5f6a1b2` |
| `bluefin-nvidia` | `:testing` | `sha256:c3d4e5f6a7b8c9d0` |

### Changes since last stable

**54 commits** ahead of stable · [Compare main…testing ↗](compare-url)

<details>
<summary>Recent commits (showing last 10)</summary>
...
</details>

---
_✅ Merge to publish the stable release once the checklist above is green._
```

After the gate job runs, only the `<!-- gate-section-start/end -->` block is replaced:

```markdown
<!-- gate-section-start -->
### Release checklist

| Check | Status | Details |
|---|---|---|
| Digest resolution | ✅ passed | 2 variants resolved from `:testing` |
| Cosign signatures | ✅ passed | All signatures verified via Sigstore |
| E2E (smoke) | ✅ passed | [Run 27398765432](run-url) · 18 min ago |
<!-- gate-section-end -->
```

---

## File structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/render_pr_body.py` | **Create** | Builds the full PR body (promote job path). Pure Python stdlib. |
| `scripts/render_gate_section.py` | **Create** | Builds just the gate checklist section for targeted body update. |
| `tests/test_render_pr_body.py` | **Create** | Unit tests for `render_pr_body.py`. |
| `tests/test_render_gate_section.py` | **Create** | Unit tests for `render_gate_section.py`. |
| `tests/conftest.py` | No change | `scripts/` already on `sys.path`. |
| `.github/workflows/reusable-promote-squash.yml` | **Modify** | Add days-since-stable, git-log, and render steps; update title + body; add `push: testing` trigger doc note. |
| `.github/workflows/reusable-promote.yml` | **Modify** | Add days-since-stable and render steps; update title + body. |
| `.github/workflows/reusable-release-gate.yml` | **Modify** | Add step to call `render_gate_section.py` and update PR body gate section. |
| `docs/skills/factory-operations.md` | **Modify** | Document PR format, title convention, gate-section markers, and testing-push trigger. |

---

## Task 1: Write failing tests for `render_pr_body.py`

**Files:**
- Create: `tests/test_render_pr_body.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_render_pr_body.py
"""Unit tests for render_pr_body.py — promotion PR body generation."""
import json
import sys
import pytest
import render_pr_body


VARIANTS_NO_DIGEST = [
    {"image": "bluefin"},
    {"image": "bluefin-nvidia"},
]

VARIANTS_WITH_DIGEST = [
    {"image": "dakota",        "digest": "sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"},
    {"image": "dakota-nvidia", "digest": "sha256:b2c3d4e5f6a7b8c9b2c3d4e5f6a7b8c9b2c3d4e5f6a7b8c9b2c3d4e5f6a7b8c9"},
]

COMMITS = [
    {"sha": "abc1234def5678901", "subject": "feat: add new gnome extension"},
    {"sha": "def5678abc1234567", "subject": "fix: resolve display issue"},
]


class TestSectionHeader:
    def test_contains_dinosaur_emoji(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=12, last_tag="stable-20260530-abc1234",
            last_release_url="https://example.com/releases/tag/stable-20260530",
        )
        assert "🦕" in md

    def test_contains_project_name(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=12, last_tag="stable-20260530-abc1234",
            last_release_url="https://example.com/releases/tag/stable-20260530",
        )
        assert "Bluefin" in md

    def test_contains_date(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=12, last_tag="stable-20260530-abc1234",
            last_release_url="https://example.com/releases/tag/stable-20260530",
        )
        assert "2026-06-11" in md

    def test_contains_days_since_stable(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=12, last_tag="stable-20260530-abc1234",
            last_release_url="https://example.com/releases/tag/stable-20260530",
        )
        assert "12" in md
        assert "days" in md.lower()

    def test_contains_last_release_link(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=7, last_tag="stable-20260604-def5678",
            last_release_url="https://example.com/releases/tag/stable-20260604",
        )
        assert "stable-20260604-def5678" in md
        assert "https://example.com/releases/tag/stable-20260604" in md

    def test_no_previous_release(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=None, last_tag=None, last_release_url=None,
        )
        assert "🦕" in md
        assert "2026-06-11" in md
        # Should not crash and should omit the days-since line


class TestSectionGatePlaceholder:
    def test_contains_start_marker(self):
        md = render_pr_body._section_gate_placeholder()
        assert "<!-- gate-section-start -->" in md

    def test_contains_end_marker(self):
        md = render_pr_body._section_gate_placeholder()
        assert "<!-- gate-section-end -->" in md

    def test_contains_checking_placeholders(self):
        md = render_pr_body._section_gate_placeholder()
        assert "⏳" in md

    def test_has_three_checks(self):
        md = render_pr_body._section_gate_placeholder()
        assert md.count("⏳") == 3


class TestSectionVariants:
    def test_lists_variant_names(self):
        md = render_pr_body._section_variants(VARIANTS_NO_DIGEST, "testing")
        assert "bluefin" in md
        assert "bluefin-nvidia" in md

    def test_shows_source_tag(self):
        md = render_pr_body._section_variants(VARIANTS_NO_DIGEST, "testing")
        assert ":testing" in md

    def test_shows_digests_when_present(self):
        md = render_pr_body._section_variants(VARIANTS_WITH_DIGEST, "testing")
        assert "a1b2c3d4e5f6a1b2" in md

    def test_omits_digest_column_when_absent(self):
        md = render_pr_body._section_variants(VARIANTS_NO_DIGEST, "testing")
        assert "sha256:" not in md

    def test_is_markdown_table(self):
        md = render_pr_body._section_variants(VARIANTS_NO_DIGEST, "testing")
        assert "|" in md
        assert "---" in md


class TestSectionCommits:
    def test_returns_empty_when_no_commits(self):
        md = render_pr_body._section_commits(0, [], None)
        assert md == ""

    def test_shows_commit_count(self):
        md = render_pr_body._section_commits(47, COMMITS, "https://example.com/compare")
        assert "47" in md

    def test_shows_compare_url(self):
        md = render_pr_body._section_commits(3, COMMITS, "https://example.com/compare/main...testing")
        assert "https://example.com/compare/main...testing" in md

    def test_shows_commit_subjects(self):
        md = render_pr_body._section_commits(3, COMMITS, None)
        assert "feat: add new gnome extension" in md

    def test_commit_shas_shortened_to_7(self):
        md = render_pr_body._section_commits(3, COMMITS, None)
        assert "abc1234" in md
        assert "abc1234def5678901" not in md  # full SHA should not appear

    def test_is_collapsible_details_block(self):
        md = render_pr_body._section_commits(3, COMMITS, None)
        assert "<details>" in md
        assert "</details>" in md


class TestBuildTitle:
    def test_contains_primary_image_name(self):
        assert "bluefin" in render_pr_body.build_title("bluefin", "2026-06-11")

    def test_contains_date(self):
        assert "2026-06-11" in render_pr_body.build_title("bluefin", "2026-06-11")

    def test_conventional_commit_prefix(self):
        assert render_pr_body.build_title("bluefin-lts", "2026-06-11").startswith("ci(promote):")

    def test_contains_direction(self):
        t = render_pr_body.build_title("dakota", "2026-06-11")
        assert "testing" in t and "stable" in t

    def test_consistent_format_across_images(self):
        for image in ("bluefin", "bluefin-lts", "dakota"):
            assert render_pr_body.build_title(image, "2026-06-11").startswith("ci(promote):")


class TestMainRender:
    def _run(self, tmp_path, extra_args=None):
        out = tmp_path / "pr-body.md"
        old = sys.argv
        sys.argv = [
            "render_pr_body.py",
            "--project-name", "Bluefin",
            "--primary-image", "bluefin",
            "--variants-json", json.dumps(VARIANTS_NO_DIGEST),
            "--repo", "projectbluefin/bluefin",
            "--run-url", "https://github.com/projectbluefin/bluefin/actions/runs/99",
            "--date", "2026-06-11",
            "--days-since-stable", "12",
            "--last-release-tag", "stable-20260530-abc1234",
            "--last-release-url", "https://github.com/projectbluefin/bluefin/releases/tag/stable-20260530-abc1234",
            "--output", str(out),
        ] + (extra_args or [])
        try:
            render_pr_body.main()
        finally:
            sys.argv = old
        return out.read_text()

    def test_squash_render_produces_file(self, tmp_path):
        body = self._run(tmp_path, [
            "--commit-count", "54",
            "--commits-json", json.dumps(COMMITS),
            "--compare-url", "https://github.com/projectbluefin/bluefin/compare/main...testing",
        ])
        assert "Bluefin" in body
        assert "2026-06-11" in body
        assert "54" in body
        assert "🦕" in body
        assert "12" in body and "days" in body.lower()
        assert "<!-- gate-section-start -->" in body
        assert "<!-- gate-section-end -->" in body

    def test_digest_render_produces_file(self, tmp_path):
        body = self._run(tmp_path, [
            "--variants-json", json.dumps(VARIANTS_WITH_DIGEST),
        ])
        assert "🦕" in body
        assert "a1b2c3d4e5f6a1b2" in body

    def test_no_previous_release_render(self, tmp_path):
        out = tmp_path / "pr-body.md"
        old = sys.argv
        sys.argv = [
            "render_pr_body.py",
            "--project-name", "Bluefin",
            "--primary-image", "bluefin",
            "--variants-json", json.dumps(VARIANTS_NO_DIGEST),
            "--repo", "projectbluefin/bluefin",
            "--run-url", "https://github.com/projectbluefin/bluefin/actions/runs/1",
            "--date", "2026-06-11",
            "--output", str(out),
        ]
        try:
            render_pr_body.main()
        finally:
            sys.argv = old
        body = out.read_text()
        assert "🦕" in body
        assert "<!-- gate-section-start -->" in body
```

- [ ] **Step 2: Run tests, confirm they fail**

```bash
cd /var/home/jorge/src/actions
python3 -m pytest tests/test_render_pr_body.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'render_pr_body'`

---

## Task 2: Implement `scripts/render_pr_body.py`

**Files:**
- Create: `scripts/render_pr_body.py`

- [ ] **Step 1: Write the implementation**

```python
#!/usr/bin/env python3
"""
render_pr_body.py — Generate the promotion PR body (testing → stable).

Called by both reusable-promote-squash.yml and reusable-promote.yml.
The body contains HTML marker comments around the gate section so the gate
job can do a targeted replacement without touching the rest of the body.

Usage (squash workflow — has git log):
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

Usage (digest workflow — digests in variants, no git log):
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

The gate section uses HTML markers for targeted update:
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
        days_line = (
            f"> **{days_ago} day{'s' if days_ago != 1 else ''} since the last stable release**"
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
            short  = (
                f"`sha256:{digest[7:23]}`"
                if digest.startswith("sha256:")
                else f"`{digest[:16]}`"
            )
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
    intro = f"**{count} commit{'s' if count != 1 else ''}** ahead of stable{compare_link}\n"

    if not commits:
        return "### Changes since last stable\n\n" + intro

    rows = "\n".join(
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
    return f"ci(promote): {primary_image} testing → stable {date}"


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Render promotion PR body")
    ap.add_argument("--project-name",       required=True)
    ap.add_argument("--primary-image",      required=True)
    ap.add_argument("--variants-json",      required=True)
    ap.add_argument("--repo",               required=True)
    ap.add_argument("--run-url",            required=True)
    ap.add_argument("--date",               required=True)
    ap.add_argument("--days-since-stable",  type=int, default=None)
    ap.add_argument("--last-release-tag",   default="")
    ap.add_argument("--last-release-url",   default="")
    ap.add_argument("--commit-count",       type=int, default=0)
    ap.add_argument("--commits-json",       default="[]")
    ap.add_argument("--compare-url",        default="")
    ap.add_argument("--source-tag",         default="testing")
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
```

- [ ] **Step 2: Run tests — all should pass**

```bash
cd /var/home/jorge/src/actions
python3 -m pytest tests/test_render_pr_body.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run full suite — no regressions**

```bash
python3 -m pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add scripts/render_pr_body.py tests/test_render_pr_body.py
git commit -m "feat(promote): add render_pr_body.py — Design C PR body with gate markers"
```

---

## Task 3: Write failing tests then implement `scripts/render_gate_section.py`

**Files:**
- Create: `tests/test_render_gate_section.py`
- Create: `scripts/render_gate_section.py`

This script is called by the gate job to replace the `<!-- gate-section-start/end -->` block in the existing PR body.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_render_gate_section.py
"""Unit tests for render_gate_section.py — gate checklist section updater."""
import json
import sys
import pytest
import render_gate_section

GATE_START = "<!-- gate-section-start -->"
GATE_END   = "<!-- gate-section-end -->"

FULL_BODY = """\
## 🦕 Bluefin testing → stable · 2026-06-11

> **12 days since the last stable release**

<!-- gate-section-start -->
### Release checklist

| Check | Status | Details |
|---|---|---|
| Digest resolution | ⏳ checking… | — |
| Cosign signatures | ⏳ checking… | — |
| E2E | ⏳ checking… | — |
<!-- gate-section-end -->

### Variants being promoted

| Variant | Tag |
|---|---|
| `bluefin` | `:testing` |
"""

GATE_ARGS_PASSED = {
    "resolve_ok": "true",
    "resolve_summary": "2 variants resolved.",
    "verify_ok": "true",
    "verify_summary": "All signatures verified.",
    "e2e_state": "passed",
    "e2e_summary": "Smoke suite passed.",
    "e2e_details": "https://github.com/example/runs/99",
    "ready": "true",
}

GATE_ARGS_BLOCKED = {
    "resolve_ok": "true",
    "resolve_summary": "2 variants resolved.",
    "verify_ok": "false",
    "verify_summary": "Signature verification failed for bluefin-nvidia.",
    "e2e_state": "skipped",
    "e2e_summary": "E2E disabled by caller.",
    "e2e_details": "",
    "ready": "false",
}


class TestBuildGateSection:
    def test_contains_start_marker(self):
        section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        assert GATE_START in section

    def test_contains_end_marker(self):
        section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        assert GATE_END in section

    def test_passed_shows_green_checkmarks(self):
        section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        assert "✅" in section

    def test_failed_shows_red_cross(self):
        section = render_gate_section.build_gate_section(**GATE_ARGS_BLOCKED)
        assert "❌" in section

    def test_skipped_shows_skipped(self):
        section = render_gate_section.build_gate_section(**GATE_ARGS_BLOCKED)
        assert "skipped" in section.lower() or "⏭️" in section

    def test_resolve_summary_present(self):
        section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        assert "2 variants resolved" in section

    def test_verify_summary_present(self):
        section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        assert "All signatures verified" in section

    def test_e2e_summary_present(self):
        section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        assert "Smoke suite passed" in section

    def test_e2e_details_link_present(self):
        section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        assert "https://github.com/example/runs/99" in section


class TestReplaceGateSection:
    def test_replaces_placeholder_with_results(self):
        new_section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        result = render_gate_section.replace_gate_section(FULL_BODY, new_section)
        assert "✅" in result
        assert "⏳" not in result

    def test_preserves_content_outside_markers(self):
        new_section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        result = render_gate_section.replace_gate_section(FULL_BODY, new_section)
        assert "🦕 Bluefin testing → stable" in result
        assert "Variants being promoted" in result

    def test_markers_still_present_after_replace(self):
        new_section = render_gate_section.build_gate_section(**GATE_ARGS_PASSED)
        result = render_gate_section.replace_gate_section(FULL_BODY, new_section)
        assert GATE_START in result
        assert GATE_END in result

    def test_raises_when_markers_missing(self):
        with pytest.raises(ValueError, match="gate-section"):
            render_gate_section.replace_gate_section("no markers here", "anything")


class TestMainRenderGate:
    def test_main_writes_updated_body(self, tmp_path):
        body_in  = tmp_path / "body-in.md"
        body_out = tmp_path / "body-out.md"
        body_in.write_text(FULL_BODY)
        old = sys.argv
        sys.argv = [
            "render_gate_section.py",
            "--body-file",      str(body_in),
            "--output",         str(body_out),
            "--resolve-ok",     "true",
            "--resolve-summary","2 variants resolved.",
            "--verify-ok",      "true",
            "--verify-summary", "All signatures verified.",
            "--e2e-state",      "passed",
            "--e2e-summary",    "Smoke suite passed.",
            "--e2e-details",    "https://github.com/example/runs/99",
            "--ready",          "true",
        ]
        try:
            render_gate_section.main()
        finally:
            sys.argv = old
        result = body_out.read_text()
        assert "✅" in result
        assert "⏳" not in result
        assert "🦕 Bluefin" in result  # preserved
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
python3 -m pytest tests/test_render_gate_section.py -v 2>&1 | head -5
```

Expected: `ModuleNotFoundError: No module named 'render_gate_section'`

- [ ] **Step 3: Implement `scripts/render_gate_section.py`**

```python
#!/usr/bin/env python3
"""
render_gate_section.py — Replace the gate checklist section in a promotion PR body.

The promote job writes the PR body with <!-- gate-section-start/end --> markers
and ⏳ placeholders. After gate checks complete, this script is called with the
actual results to produce an updated body file.

Usage:
    python3 render_gate_section.py \\
        --body-file      /tmp/current-pr-body.md \\
        --output         /tmp/updated-pr-body.md \\
        --resolve-ok     true \\
        --resolve-summary "2 variants resolved." \\
        --verify-ok      true \\
        --verify-summary "All signatures verified." \\
        --e2e-state      passed \\
        --e2e-summary    "Smoke suite passed." \\
        --e2e-details    "https://github.com/.../runs/99" \\
        --ready          true
"""
import argparse
import re
import sys

GATE_START = "<!-- gate-section-start -->"
GATE_END   = "<!-- gate-section-end -->"

_STATUS_ICON = {
    "passed":  "✅",
    "failed":  "❌",
    "skipped": "⏭️",
    "waiting": "⏳",
    "stale":   "⚠️",
    "error":   "❌",
}


# ── Core functions ─────────────────────────────────────────────────────────────

def _icon(ok_str: str, state: str = "") -> str:
    if state in _STATUS_ICON:
        return _STATUS_ICON[state]
    return "✅" if ok_str == "true" else "❌"


def build_gate_section(
    *,
    resolve_ok: str,
    resolve_summary: str,
    verify_ok: str,
    verify_summary: str,
    e2e_state: str,
    e2e_summary: str,
    e2e_details: str,
    ready: str,
) -> str:
    e2e_icon = _icon("", e2e_state)

    e2e_detail_cell = e2e_summary
    if e2e_details and e2e_details.startswith("http"):
        e2e_detail_cell = f"[{e2e_summary}]({e2e_details})"
    elif e2e_details:
        e2e_detail_cell = f"{e2e_summary} {e2e_details}".strip()

    rows = "\n".join([
        f"| Digest resolution | {_icon(resolve_ok)} passed | {resolve_summary} |",
        f"| Cosign signatures | {_icon(verify_ok)} {'passed' if verify_ok == 'true' else 'failed'} | {verify_summary} |",
        f"| E2E | {e2e_icon} {e2e_state} | {e2e_detail_cell} |",
    ])

    overall = "✅ All checks passed" if ready == "true" else "❌ Gate blocked"

    return (
        f"{GATE_START}\n"
        "### Release checklist\n\n"
        f"**{overall}**\n\n"
        "| Check | Status | Details |\n"
        "|---|---|---|\n"
        f"{rows}\n"
        f"{GATE_END}\n"
    )


def replace_gate_section(body: str, new_section: str) -> str:
    if GATE_START not in body or GATE_END not in body:
        raise ValueError(
            f"PR body does not contain gate-section markers "
            f"({GATE_START!r} / {GATE_END!r}). Cannot update."
        )
    pattern = re.compile(
        re.escape(GATE_START) + r".*?" + re.escape(GATE_END),
        re.DOTALL,
    )
    return pattern.sub(new_section.rstrip("\n"), body)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Update gate checklist section in PR body")
    ap.add_argument("--body-file",       required=True, help="Path to current PR body markdown")
    ap.add_argument("--output",          required=True, help="Path to write updated body")
    ap.add_argument("--resolve-ok",      required=True)
    ap.add_argument("--resolve-summary", required=True)
    ap.add_argument("--verify-ok",       required=True)
    ap.add_argument("--verify-summary",  required=True)
    ap.add_argument("--e2e-state",       required=True)
    ap.add_argument("--e2e-summary",     required=True)
    ap.add_argument("--e2e-details",     default="")
    ap.add_argument("--ready",           required=True)
    args = ap.parse_args()

    with open(args.body_file, encoding="utf-8") as f:
        current_body = f.read()

    new_section  = build_gate_section(
        resolve_ok=args.resolve_ok,
        resolve_summary=args.resolve_summary,
        verify_ok=args.verify_ok,
        verify_summary=args.verify_summary,
        e2e_state=args.e2e_state,
        e2e_summary=args.e2e_summary,
        e2e_details=args.e2e_details,
        ready=args.ready,
    )
    updated_body = replace_gate_section(current_body, new_section)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(updated_body)
    print(f"Gate section updated: {args.output} ({len(updated_body):,} chars)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

```bash
python3 -m pytest tests/test_render_gate_section.py tests/test_render_pr_body.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/render_gate_section.py tests/test_render_gate_section.py
git commit -m "feat(promote): add render_gate_section.py for targeted gate checklist update"
```

---

## Task 4: Update `reusable-promote-squash.yml`

**Files:**
- Modify: `.github/workflows/reusable-promote-squash.yml`

Changes: (1) fetch days-since-stable, (2) collect git log, (3) render PR body, (4) new consistent title, (5) add `push: [testing]` trigger note.

- [ ] **Step 1: Add `push` trigger for testing branch**

Find:
```yaml
on:
  workflow_call:
```

Replace with:
```yaml
on:
  workflow_call:
  # Callers should also add:
  #   push:
  #     branches: [testing]
  # so the PR body updates on every merge to testing.
```

- [ ] **Step 2: Add three new steps before `Upsert promotion PR`**

Find:
```yaml
      - name: Upsert promotion PR
        if: steps.compare.outputs.sync_needed == 'true'
        id: upsert
```

Insert before it:
```yaml
      - name: Fetch last stable release metadata
        if: steps.compare.outputs.sync_needed == 'true'
        id: last-release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          RELEASE_JSON=$(gh release list \
            --repo "${{ github.repository }}" \
            --limit 1 \
            --json tagName,publishedAt,url \
            --jq '.[0]' 2>/dev/null || echo '{}')

          TAG=$(echo "${RELEASE_JSON}" | jq -r '.tagName // empty')
          PUBLISHED=$(echo "${RELEASE_JSON}" | jq -r '.publishedAt // empty')
          URL=$(echo "${RELEASE_JSON}" | jq -r '.url // empty')
          # Convert API URL to html URL (strip /api/v3 prefix, replace /repos/ path)
          HTML_URL=$(echo "${URL}" | sed 's|api\.github\.com/repos/|github.com/|; s|/releases/[0-9]*$||')
          HTML_URL="https://github.com/${{ github.repository }}/releases/tag/${TAG}"

          if [[ -n "${TAG}" && -n "${PUBLISHED}" ]]; then
            DAYS=$(( ( $(date +%s) - $(date -d "${PUBLISHED}" +%s) ) / 86400 ))
            echo "days=${DAYS}"      >> "$GITHUB_OUTPUT"
            echo "tag=${TAG}"        >> "$GITHUB_OUTPUT"
            echo "url=${HTML_URL}"   >> "$GITHUB_OUTPUT"
          else
            echo "days="             >> "$GITHUB_OUTPUT"
            echo "tag="              >> "$GITHUB_OUTPUT"
            echo "url="              >> "$GITHUB_OUTPUT"
          fi

      - name: Collect git log for PR body
        if: steps.compare.outputs.sync_needed == 'true'
        id: gitlog
        run: |
          set -euo pipefail
          COUNT=$(git rev-list --count origin/main..origin/testing 2>/dev/null || echo 0)
          echo "count=${COUNT}" >> "$GITHUB_OUTPUT"

          COMMITS_JSON=$(git log origin/main..origin/testing \
            --pretty=format:'{"sha":"%H","subject":"%s"}' \
            --max-count=20 \
            | jq -s '.' 2>/dev/null || echo '[]')
          echo "commits_json=${COMMITS_JSON}" >> "$GITHUB_OUTPUT"
          echo "compare_url=https://github.com/${{ github.repository }}/compare/main...testing" >> "$GITHUB_OUTPUT"

      - name: Render promotion PR body
        if: steps.compare.outputs.sync_needed == 'true'
        id: render
        env:
          VARIANTS:        ${{ inputs.variants }}
          RUN_URL:         ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
          COMMIT_COUNT:    ${{ steps.gitlog.outputs.count }}
          COMMITS_JSON:    ${{ steps.gitlog.outputs.commits_json }}
          COMPARE_URL:     ${{ steps.gitlog.outputs.compare_url }}
          DAYS_AGO:        ${{ steps.last-release.outputs.days }}
          LAST_TAG:        ${{ steps.last-release.outputs.tag }}
          LAST_URL:        ${{ steps.last-release.outputs.url }}
        run: |
          set -euo pipefail
          PRIMARY_IMAGE=$(echo "${VARIANTS}" | jq -r 'if .[0] | type == "string" then .[0] else .[0].image end')
          PROJECT_NAME=$(echo "${PRIMARY_IMAGE}" | sed 's/-/ /g; s/\b\(.\)/\u\1/g')
          DATE="$(date -u +%Y-%m-%d)"

          DAYS_ARG=()
          [[ -n "${DAYS_AGO}" ]] && DAYS_ARG+=(--days-since-stable "${DAYS_AGO}")
          TAG_ARG=()
          [[ -n "${LAST_TAG}" ]] && TAG_ARG+=(--last-release-tag "${LAST_TAG}" --last-release-url "${LAST_URL}")

          python3 scripts/render_pr_body.py \
            --project-name   "${PROJECT_NAME}" \
            --primary-image  "${PRIMARY_IMAGE}" \
            --variants-json  "${VARIANTS}" \
            --repo           "${{ github.repository }}" \
            --run-url        "${RUN_URL}" \
            --date           "${DATE}" \
            "${DAYS_ARG[@]}" \
            "${TAG_ARG[@]}" \
            --commit-count   "${COMMIT_COUNT}" \
            --commits-json   "${COMMITS_JSON}" \
            --compare-url    "${COMPARE_URL}" \
            --output         /tmp/pr-body.md

          echo "pr_title=ci(promote): ${PRIMARY_IMAGE} testing → stable ${DATE}" >> "$GITHUB_OUTPUT"

```

- [ ] **Step 3: Update `Upsert promotion PR` to use the rendered title and body**

Find inside the `Upsert promotion PR` step's `run:` block:
```yaml
          TITLE="chore: promote testing to main"
          BODY=$(printf '%s\n' \
            "## Automated testing → main promotion" \
            "" \
            "This PR is maintained by \`.github/workflows/promote-testing-to-main.yml\`." \
            "" \
            "- Testing SHA: \`${TESTING_SHA}\`" \
            "- Workflow run: ${RUN_URL}" \
            "" \
            "The squash branch is rebuilt fresh on every run — always clean, no merge conflicts.")
```

Replace with:
```yaml
          TITLE="${{ steps.render.outputs.pr_title }}"
```

And remove `RUN_URL` from this step's `env:` block (it was only used for the old body).

Remove from the `env:` block:
```yaml
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
```

Update the `gh pr create` and `gh pr edit` calls to use `--body-file /tmp/pr-body.md` instead of `--body "$BODY"`:

Find:
```yaml
          if [ -n "$PR_NUMBER" ]; then
            gh pr edit "$PR_NUMBER" \
              --repo "${{ github.repository }}" \
              --title "$TITLE" \
              --body "$BODY"
```

Replace with:
```yaml
          if [ -n "$PR_NUMBER" ]; then
            gh pr edit "$PR_NUMBER" \
              --repo "${{ github.repository }}" \
              --title "$TITLE" \
              --body-file /tmp/pr-body.md
```

Find:
```yaml
            PR_NUMBER=$(gh pr create \
              --repo "${{ github.repository }}" \
              --base main \
              --head "$PROMOTION_BRANCH" \
              --title "$TITLE" \
              --body "$BODY" \
```

Replace with:
```yaml
            PR_NUMBER=$(gh pr create \
              --repo "${{ github.repository }}" \
              --base main \
              --head "$PROMOTION_BRANCH" \
              --title "$TITLE" \
              --body-file /tmp/pr-body.md \
```

- [ ] **Step 4: Lint**

```bash
actionlint .github/workflows/reusable-promote-squash.yml
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/reusable-promote-squash.yml
git commit -m "feat(promote): Design C PR body in squash workflow — 🦕, days-since-stable, gate markers"
```

---

## Task 5: Update `reusable-promote.yml` (dakota — digest workflow)

**Files:**
- Modify: `.github/workflows/reusable-promote.yml`

- [ ] **Step 1: Add three new steps before `Open or update promotion PR`**

Find:
```yaml
      - name: Open or update promotion PR
        if: steps.branch.outputs.changed == 'true'
        id: pr
```

Insert before it:
```yaml
      - name: Fetch last stable release metadata
        if: steps.branch.outputs.changed == 'true'
        id: last-release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          RELEASE_JSON=$(gh release list \
            --repo "${{ github.repository }}" \
            --limit 1 \
            --json tagName,publishedAt,url \
            --jq '.[0]' 2>/dev/null || echo '{}')

          TAG=$(echo "${RELEASE_JSON}" | jq -r '.tagName // empty')
          PUBLISHED=$(echo "${RELEASE_JSON}" | jq -r '.publishedAt // empty')
          HTML_URL="https://github.com/${{ github.repository }}/releases/tag/${TAG}"

          if [[ -n "${TAG}" && -n "${PUBLISHED}" ]]; then
            DAYS=$(( ( $(date +%s) - $(date -d "${PUBLISHED}" +%s) ) / 86400 ))
            echo "days=${DAYS}"    >> "$GITHUB_OUTPUT"
            echo "tag=${TAG}"      >> "$GITHUB_OUTPUT"
            echo "url=${HTML_URL}" >> "$GITHUB_OUTPUT"
          else
            echo "days="           >> "$GITHUB_OUTPUT"
            echo "tag="            >> "$GITHUB_OUTPUT"
            echo "url="            >> "$GITHUB_OUTPUT"
          fi

      - name: Build variants-with-digests JSON
        if: steps.branch.outputs.changed == 'true'
        id: variants-json
        env:
          VARIANTS: ${{ inputs.variants }}
        run: |
          set -euo pipefail
          VARIANTS_WITH_DIGESTS=$(python3 - <<'PYEOF'
          import json, sys, os

          variants_raw = json.loads(os.environ["VARIANTS"])
          import yaml
          with open(".github/release-state.yaml") as f:
              state = yaml.safe_load(f)
          testing_digests = state.get("testing", {})
          result = []
          for v in variants_raw:
              name = v if isinstance(v, str) else v.get("image", "")
              digest = testing_digests.get(name, "")
              result.append({"image": name, "digest": digest})
          print(json.dumps(result))
          PYEOF
          )
          echo "json=${VARIANTS_WITH_DIGESTS}" >> "$GITHUB_OUTPUT"

      - name: Render promotion PR body
        if: steps.branch.outputs.changed == 'true'
        id: render
        env:
          VARIANTS_JSON: ${{ steps.variants-json.outputs.json }}
          VARIANTS:      ${{ inputs.variants }}
          RUN_URL:       ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
          DAYS_AGO:      ${{ steps.last-release.outputs.days }}
          LAST_TAG:      ${{ steps.last-release.outputs.tag }}
          LAST_URL:      ${{ steps.last-release.outputs.url }}
        run: |
          set -euo pipefail
          PRIMARY_IMAGE=$(echo "${VARIANTS}" | jq -r 'if .[0] | type == "string" then .[0] else .[0].image end')
          PROJECT_NAME=$(echo "${PRIMARY_IMAGE}" | sed 's/-/ /g; s/\b\(.\)/\u\1/g')
          DATE="$(date -u +%Y-%m-%d)"

          DAYS_ARG=()
          [[ -n "${DAYS_AGO}" ]] && DAYS_ARG+=(--days-since-stable "${DAYS_AGO}")
          TAG_ARG=()
          [[ -n "${LAST_TAG}" ]] && TAG_ARG+=(--last-release-tag "${LAST_TAG}" --last-release-url "${LAST_URL}")

          python3 scripts/render_pr_body.py \
            --project-name  "${PROJECT_NAME}" \
            --primary-image "${PRIMARY_IMAGE}" \
            --variants-json "${VARIANTS_JSON}" \
            --repo          "${{ github.repository }}" \
            --run-url       "${RUN_URL}" \
            --date          "${DATE}" \
            "${DAYS_ARG[@]}" \
            "${TAG_ARG[@]}" \
            --output        /tmp/pr-body.md

          echo "pr_title=ci(promote): ${PRIMARY_IMAGE} testing → stable ${DATE}" >> "$GITHUB_OUTPUT"

```

- [ ] **Step 2: Update `Open or update promotion PR` — replace old title/body generation**

Find inside that step's `run:` block:
```yaml
          FIRST_DIGEST=$(grep -m1 '^  [a-z]' .github/release-state.yaml \
            | awk '{print $2}' | tr -d '"' | cut -c8-23)
          PR_TITLE="ci: promote testing images to stable (${FIRST_DIGEST})"

          {
            echo "## Promote :testing → :stable"
            echo ""
            echo "Merge this PR to publish a stable release."
            echo ""
            echo '```yaml'
            cat .github/release-state.yaml
            echo '```'
          } > /tmp/pr-body.md
```

Replace with:
```yaml
          PR_TITLE="${{ steps.render.outputs.pr_title }}"
```

Update both `gh pr edit` and `gh pr create` calls to use `--body-file /tmp/pr-body.md` instead of `--body-file /tmp/pr-body.md` (already correct if body was written by render step).

Verify the `gh pr edit` and `gh pr create` calls reference `--body-file /tmp/pr-body.md` (they should already since the body was at that path; just confirm `PR_TITLE` now comes from the render step output).

- [ ] **Step 3: Lint**

```bash
actionlint .github/workflows/reusable-promote.yml
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/reusable-promote.yml
git commit -m "feat(promote): Design C PR body in digest workflow — 🦕, days-since-stable, gate markers"
```

---

## Task 6: Update `reusable-release-gate.yml` — write gate results into PR body

**Files:**
- Modify: `.github/workflows/reusable-release-gate.yml`

The gate job already posts a sticky comment. Now it also updates the PR body gate section.

- [ ] **Step 1: Add a checkout step at the start of the `gate` job**

The gate job needs access to `render_gate_section.py`. It needs a checkout.

Find the first step in the `gate` job:
```yaml
      - name: Authenticate to GHCR for skopeo reads
```

Insert before it:
```yaml
      - name: Checkout (for gate section script)
        uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6

```

- [ ] **Step 2: Add a new step after `Aggregate gate result` to update the PR body**

Find:
```yaml
      - name: Post or update sticky release status comment
```

Insert before it:
```yaml
      - name: Update PR body gate section
        if: inputs.pr_number != ''
        env:
          GH_TOKEN: ${{ github.token }}
          INPUT_PR_NUMBER: ${{ inputs.pr_number }}
          RESOLVE_OK:      ${{ steps.resolve.outputs.ok }}
          RESOLVE_SUMMARY: ${{ steps.resolve.outputs.summary }}
          VERIFY_OK:       ${{ steps.verify.outputs.ok }}
          VERIFY_SUMMARY:  ${{ steps.verify.outputs.summary }}
          E2E_STATE:       ${{ steps.e2e.outputs.state }}
          E2E_SUMMARY:     ${{ steps.e2e.outputs.summary }}
          E2E_DETAILS:     ${{ steps.e2e.outputs.details }}
          READY:           ${{ steps.aggregate.outputs.ready }}
          REPO:            ${{ inputs.repo }}
        run: |
          set -euo pipefail

          # Fetch current PR body
          gh pr view "${INPUT_PR_NUMBER}" \
            --repo "${REPO}" \
            --json body \
            --jq '.body' > /tmp/current-pr-body.md

          # Skip if the PR body doesn't have our gate markers
          # (e.g. old-format PR from before this feature shipped)
          if ! grep -q '<!-- gate-section-start -->' /tmp/current-pr-body.md; then
            echo "::notice::PR body does not contain gate section markers — skipping body update (comment still posted below)."
            exit 0
          fi

          python3 scripts/render_gate_section.py \
            --body-file      /tmp/current-pr-body.md \
            --output         /tmp/updated-pr-body.md \
            --resolve-ok     "${RESOLVE_OK}" \
            --resolve-summary "${RESOLVE_SUMMARY}" \
            --verify-ok      "${VERIFY_OK}" \
            --verify-summary "${VERIFY_SUMMARY}" \
            --e2e-state      "${E2E_STATE}" \
            --e2e-summary    "${E2E_SUMMARY}" \
            --e2e-details    "${E2E_DETAILS:-}" \
            --ready          "${READY}"

          gh pr edit "${INPUT_PR_NUMBER}" \
            --repo "${REPO}" \
            --body-file /tmp/updated-pr-body.md
          echo "PR body gate section updated."

```

- [ ] **Step 3: Lint**

```bash
actionlint .github/workflows/reusable-release-gate.yml
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/reusable-release-gate.yml
git commit -m "feat(gate): update PR body gate section after checks complete"
```

---

## Task 7: Document the convention and trigger setup

**Files:**
- Modify: `docs/skills/factory-operations.md`

- [ ] **Step 1: Append promotion PR section**

```markdown
## Promotion PR conventions

### Title format

```
ci(promote): <primary-image> testing → stable YYYY-MM-DD
```

Examples:
- `ci(promote): bluefin testing → stable 2026-06-11`
- `ci(promote): bluefin-lts testing → stable 2026-06-11`
- `ci(promote): dakota testing → stable 2026-06-11`

The date is the date the promote workflow ran. The title is overwritten
(rolling update) on every run.

### Body structure (Design C)

```
## 🦕 <Project> testing → stable · YYYY-MM-DD

> X days since the last stable release · [tag ↗](release-url)
> Auto-maintained · Updated ISO-timestamp · [Run ↗](run-url)

<!-- gate-section-start -->
### Release checklist
| Check | Status | Details |
|---|---|---|
| Digest resolution | ✅/❌ | ... |
| Cosign signatures | ✅/❌ | ... |
| E2E              | ✅/❌ | ... |
<!-- gate-section-end -->

### Variants being promoted
(table of images + tags + digests when available)

### Changes since last stable
(commit count + collapsible commit log; squash workflow only)

---
_Merge to publish..._
```

The promote job writes the body with ⏳ placeholders in the gate section.
The gate job replaces only the `<!-- gate-section-start/end -->` block with
live results, preserving the rest of the body.

### Scripts

| Script | Called by | Purpose |
|---|---|---|
| `scripts/render_pr_body.py` | promote job | Full PR body, ⏳ gate placeholders |
| `scripts/render_gate_section.py` | gate job | Replaces only the gate section in existing body |

### Trigger setup — running on every push to testing

Consumer repos should call the promote workflow on `push` to `testing`
in addition to their existing schedule/dispatch triggers:

```yaml
# In the consumer repo's promote-testing-to-main.yml
on:
  push:
    branches: [testing]
  schedule:
    - cron: '0 9 * * *'
  workflow_dispatch:

jobs:
  promote:
    uses: projectbluefin/actions/.github/workflows/reusable-promote-squash.yml@v1
    ...
```

This ensures the PR body refreshes (new commit count, updated timestamp)
on every merge to the testing branch, not just on the nightly schedule.
```

- [ ] **Step 2: Commit**

```bash
git add docs/skills/factory-operations.md
git commit -m "docs(skills): document Design C promotion PR format and testing-push trigger"
```

---

## Task 8: End-to-end validation

- [ ] **Step 1: Full test suite**

```bash
cd /var/home/jorge/src/actions
python3 -m pytest tests/ -v
```

Expected: all tests pass. New test files `test_render_pr_body.py` and `test_render_gate_section.py` appear.

- [ ] **Step 2: Lint all three modified workflows**

```bash
actionlint \
  .github/workflows/reusable-promote-squash.yml \
  .github/workflows/reusable-promote.yml \
  .github/workflows/reusable-release-gate.yml
```

Expected: no output.

- [ ] **Step 3: Smoke-test squash path**

```bash
python3 scripts/render_pr_body.py \
  --project-name "Bluefin" \
  --primary-image "bluefin" \
  --variants-json '[{"image":"bluefin"},{"image":"bluefin-nvidia"}]' \
  --repo "projectbluefin/bluefin" \
  --run-url "https://github.com/projectbluefin/bluefin/actions/runs/99" \
  --date "$(date -u +%Y-%m-%d)" \
  --days-since-stable 12 \
  --last-release-tag "stable-20260530-abc1234" \
  --last-release-url "https://github.com/projectbluefin/bluefin/releases/tag/stable-20260530-abc1234" \
  --commit-count 47 \
  --commits-json '[{"sha":"abc1234def567890","subject":"feat: add gnome extension"},{"sha":"def5678abc12345","subject":"fix: display issue"}]' \
  --compare-url "https://github.com/projectbluefin/bluefin/compare/main...testing" \
  --output /tmp/smoke-squash.md && cat /tmp/smoke-squash.md
```

Expected: body with 🦕, "12 days since last stable", ⏳ gate placeholders, variants table, commit section.

- [ ] **Step 4: Smoke-test gate section update**

```bash
python3 scripts/render_gate_section.py \
  --body-file      /tmp/smoke-squash.md \
  --output         /tmp/smoke-gate-updated.md \
  --resolve-ok     "true" \
  --resolve-summary "2 variants resolved." \
  --verify-ok      "true" \
  --verify-summary "All signatures verified." \
  --e2e-state      "passed" \
  --e2e-summary    "Smoke suite passed." \
  --e2e-details    "https://github.com/projectbluefin/testsuite/actions/runs/12345" \
  --ready          "true" && diff /tmp/smoke-squash.md /tmp/smoke-gate-updated.md
```

Expected: diff shows only the gate section changed (⏳ → ✅).

- [ ] **Step 5: Smoke-test digest path**

```bash
python3 scripts/render_pr_body.py \
  --project-name "Dakota" \
  --primary-image "dakota" \
  --variants-json '[{"image":"dakota","digest":"sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"},{"image":"dakota-nvidia","digest":"sha256:b2c3d4e5f6a7b8c9b2c3d4e5f6a7b8c9b2c3d4e5f6a7b8c9b2c3d4e5f6a7b8c9"}]' \
  --repo "projectbluefin/dakota" \
  --run-url "https://github.com/projectbluefin/dakota/actions/runs/42" \
  --date "$(date -u +%Y-%m-%d)" \
  --days-since-stable 5 \
  --last-release-tag "stable-20260606-def5678" \
  --last-release-url "https://github.com/projectbluefin/dakota/releases/tag/stable-20260606-def5678" \
  --output /tmp/smoke-digest.md && cat /tmp/smoke-digest.md
```

Expected: body with 🦕, "5 days since last stable", digests in variants table, no commit section.

---

## Self-review

**Spec coverage:**
- ✅ 🦕 emoji in header (replaces 🚀)
- ✅ "X days since last stable release" subtitle with link
- ✅ Gate checks inline in PR body (Design C)
- ✅ Gate section uses `<!-- gate-section-start/end -->` markers for targeted replacement
- ✅ Promote job writes ⏳ placeholders; gate job replaces with live results
- ✅ Consistent title `ci(promote): <image> testing → stable YYYY-MM-DD` across all three repos
- ✅ Squash workflow (bluefin/bluefin-lts): commit log section
- ✅ Digest workflow (dakota): digest-in-table section
- ✅ Runs on push to testing (documented for consumer callers)
- ✅ Rolling update — body overwritten on every promote run
- ✅ TDD with full test coverage of all section builders and both render paths

**Placeholder scan:** None present.

**Type consistency:**
- `_section_gate_placeholder()` → no args, always produces 3 ⏳ rows matching `GATE_START/END` markers
- `replace_gate_section(body: str, new_section: str)` — raises `ValueError` when markers absent; tested
- `build_gate_section(...)` → called by gate job; produces a new section with same markers → safe for repeated application
- `build_title(primary_image, date)` → consistent signature used in tests and main()
