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

    def test_singular_day(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=1, last_tag="stable-20260610-abc1234",
            last_release_url="https://example.com/releases/tag/stable-20260610",
        )
        assert "1 day" in md
        assert "1 days" not in md

    def test_contains_last_release_link(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=7, last_tag="stable-20260604-def5678",
            last_release_url="https://example.com/releases/tag/stable-20260604",
        )
        assert "stable-20260604-def5678" in md
        assert "https://example.com/releases/tag/stable-20260604" in md

    def test_no_previous_release_omits_days_line(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=None, last_tag=None, last_release_url=None,
        )
        assert "🦕" in md
        assert "2026-06-11" in md
        assert "days" not in md.lower()

    def test_contains_run_url(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run/99",
            days_ago=None, last_tag=None, last_release_url=None,
        )
        assert "https://example.com/run/99" in md

    def test_testing_to_stable_direction(self):
        md = render_pr_body._section_header(
            "Bluefin", "2026-06-11", "https://example.com/run",
            days_ago=None, last_tag=None, last_release_url=None,
        )
        assert "testing" in md.lower()
        assert "stable" in md.lower()


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

    def test_has_three_check_rows(self):
        md = render_pr_body._section_gate_placeholder()
        assert md.count("⏳") == 3

    def test_is_markdown_table(self):
        md = render_pr_body._section_gate_placeholder()
        assert "|" in md
        assert "---" in md


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

    def test_digest_shortened_to_16_hex(self):
        md = render_pr_body._section_variants(VARIANTS_WITH_DIGEST, "testing")
        # Full 64-char hex should not appear — only the 16-char short form
        full = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        assert full not in md
        assert "a1b2c3d4e5f6a1b2" in md


class TestSectionCommits:
    def test_returns_empty_when_no_commits(self):
        md = render_pr_body._section_commits(0, [], None)
        assert md == ""

    def test_shows_commit_count(self):
        md = render_pr_body._section_commits(47, COMMITS, "https://example.com/compare")
        assert "47" in md

    def test_singular_commit(self):
        md = render_pr_body._section_commits(1, COMMITS[:1], None)
        assert "1 commit" in md
        assert "1 commits" not in md

    def test_shows_compare_url(self):
        md = render_pr_body._section_commits(3, COMMITS, "https://example.com/compare/main...testing")
        assert "https://example.com/compare/main...testing" in md

    def test_shows_commit_subjects(self):
        md = render_pr_body._section_commits(3, COMMITS, None)
        assert "feat: add new gnome extension" in md
        assert "fix: resolve display issue" in md

    def test_commit_shas_shortened_to_7(self):
        md = render_pr_body._section_commits(3, COMMITS, None)
        assert "abc1234" in md
        assert "abc1234def5678901" not in md  # full SHA must not appear

    def test_is_collapsible_details_block(self):
        md = render_pr_body._section_commits(3, COMMITS, None)
        assert "<details>" in md
        assert "</details>" in md

    def test_pipe_in_subject_escaped(self):
        commits_with_pipe = [{"sha": "abc1234567890", "subject": "feat: add foo | bar"}]
        md = render_pr_body._section_commits(1, commits_with_pipe, None)
        # The pipe in the subject must be escaped so the table renders correctly
        assert "foo \\| bar" in md or "foo | bar" not in md.split("feat:")[1].split("\n")[0]


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
            title = render_pr_body.build_title(image, "2026-06-11")
            assert title.startswith("ci(promote):")
            assert image in title
            assert "2026-06-11" in title


class TestMainRender:
    def _run_squash(self, tmp_path):
        out = tmp_path / "pr-body.md"
        old = sys.argv
        sys.argv = [
            "render_pr_body.py",
            "--project-name",    "Bluefin",
            "--primary-image",   "bluefin",
            "--variants-json",   json.dumps(VARIANTS_NO_DIGEST),
            "--repo",            "projectbluefin/bluefin",
            "--run-url",         "https://github.com/projectbluefin/bluefin/actions/runs/99",
            "--date",            "2026-06-11",
            "--days-since-stable", "12",
            "--last-release-tag",  "stable-20260530-abc1234",
            "--last-release-url",  "https://github.com/projectbluefin/bluefin/releases/tag/stable-20260530-abc1234",
            "--commit-count",    "54",
            "--commits-json",    json.dumps(COMMITS),
            "--compare-url",     "https://github.com/projectbluefin/bluefin/compare/main...testing",
            "--output",          str(out),
        ]
        try:
            render_pr_body.main()
        finally:
            sys.argv = old
        return out.read_text()

    def test_squash_render_contains_key_elements(self, tmp_path):
        body = self._run_squash(tmp_path)
        assert "🦕" in body
        assert "Bluefin" in body
        assert "2026-06-11" in body
        assert "54" in body
        assert "12" in body and "days" in body.lower()
        assert "<!-- gate-section-start -->" in body
        assert "<!-- gate-section-end -->" in body
        assert "⏳" in body
        assert "feat: add new gnome extension" in body

    def test_digest_render_contains_key_elements(self, tmp_path):
        out = tmp_path / "pr-body.md"
        old = sys.argv
        sys.argv = [
            "render_pr_body.py",
            "--project-name",    "Dakota",
            "--primary-image",   "dakota",
            "--variants-json",   json.dumps(VARIANTS_WITH_DIGEST),
            "--repo",            "projectbluefin/dakota",
            "--run-url",         "https://github.com/projectbluefin/dakota/actions/runs/42",
            "--date",            "2026-06-11",
            "--days-since-stable", "5",
            "--last-release-tag",  "stable-20260606-def5678",
            "--last-release-url",  "https://github.com/projectbluefin/dakota/releases/tag/stable-20260606-def5678",
            "--output",          str(out),
        ]
        try:
            render_pr_body.main()
        finally:
            sys.argv = old
        body = out.read_text()
        assert "🦕" in body
        assert "Dakota" in body
        assert "a1b2c3d4e5f6a1b2" in body
        assert "<!-- gate-section-start -->" in body

    def test_no_previous_release_renders_without_error(self, tmp_path):
        out = tmp_path / "pr-body.md"
        old = sys.argv
        sys.argv = [
            "render_pr_body.py",
            "--project-name",  "Bluefin",
            "--primary-image", "bluefin",
            "--variants-json", json.dumps(VARIANTS_NO_DIGEST),
            "--repo",          "projectbluefin/bluefin",
            "--run-url",       "https://github.com/projectbluefin/bluefin/actions/runs/1",
            "--date",          "2026-06-11",
            "--output",        str(out),
        ]
        try:
            render_pr_body.main()
        finally:
            sys.argv = old
        body = out.read_text()
        assert "🦕" in body
        assert "<!-- gate-section-start -->" in body
        assert "days" not in body.lower()
