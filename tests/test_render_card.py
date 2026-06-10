"""
Unit tests for render_card.py — HTML release card generation.

Note: _screenshot() requires Playwright and is not tested here.
      These tests cover _chip(), _diff_bar(), and _build_html() which
      produce HTML strings and can run without a browser.
"""
import pytest
import render_card


# ── Sample data ───────────────────────────────────────────────────────────────

VERSIONS_NO_PREV = {
    "notable": [
        {"name": "Kernel",      "version": "6.10.0", "prev": None,    "changed": False},
        {"name": "GNOME Shell", "version": "47.1",   "prev": None,    "changed": False},
    ],
    "diff": {
        "changed_count": 0, "added_count": 0, "removed_count": 0,
        "changed": [], "added": [], "removed": [],
    },
    "has_prev": False,
    "total_packages": 423,
}

VERSIONS_WITH_PREV = {
    "notable": [
        {"name": "Kernel",      "version": "6.10.0", "prev": "6.9.14", "changed": True},
        {"name": "GNOME Shell", "version": "47.1",   "prev": "47.0",   "changed": True},
    ],
    "diff": {
        "changed_count": 2, "added_count": 1, "removed_count": 1,
        "changed": [{"name": "linux", "prev": "6.9.14", "curr": "6.10.0"}],
        "added":   [{"name": "podman", "version": "5.2.0"}],
        "removed": [{"name": "old-package", "version": "9.9.9"}],
    },
    "has_prev": True,
    "total_packages": 423,
}


# ── _chip ─────────────────────────────────────────────────────────────────────

class TestChip:
    def test_renders_label(self):
        chip = render_card._chip({"name": "Kernel", "version": "6.10.0", "changed": False})
        assert "Kernel" in chip

    def test_renders_version(self):
        chip = render_card._chip({"name": "Kernel", "version": "6.10.0", "changed": False})
        assert "6.10.0" in chip

    def test_unchanged_chip_no_prev(self):
        chip = render_card._chip({"name": "Kernel", "version": "6.10.0", "changed": False})
        assert "chip-prev" not in chip
        assert "chip-arrow" not in chip

    def test_changed_chip_shows_prev(self):
        chip = render_card._chip({
            "name": "Kernel", "version": "6.10.0",
            "prev": "6.9.14", "changed": True,
        })
        assert "6.9.14" in chip
        assert "chip-prev" in chip
        assert "chip-arrow" in chip

    def test_changed_chip_has_changed_class(self):
        chip = render_card._chip({
            "name": "Kernel", "version": "6.10.0",
            "prev": "6.9.14", "changed": True,
        })
        assert 'class="chip changed"' in chip

    def test_html_escaping(self):
        chip = render_card._chip({"name": "<b>test</b>", "version": "1.0", "changed": False})
        assert "<b>test</b>" not in chip  # must be escaped
        assert "&lt;b&gt;" in chip


# ── _diff_bar ─────────────────────────────────────────────────────────────────

class TestDiffBar:
    def test_no_prev_returns_empty(self):
        bar = render_card._diff_bar(VERSIONS_NO_PREV["diff"], has_prev=False)
        assert bar == ""

    def test_with_prev_shows_updated_count(self):
        bar = render_card._diff_bar(VERSIONS_WITH_PREV["diff"], has_prev=True)
        assert "2 updated" in bar

    def test_with_prev_shows_added_count(self):
        bar = render_card._diff_bar(VERSIONS_WITH_PREV["diff"], has_prev=True)
        assert "1 added" in bar

    def test_with_prev_shows_removed_count(self):
        bar = render_card._diff_bar(VERSIONS_WITH_PREV["diff"], has_prev=True)
        assert "1 removed" in bar

    def test_no_changes_shows_no_changes_message(self):
        no_change_diff = {
            "changed_count": 0, "added_count": 0, "removed_count": 0,
            "changed": [], "added": [], "removed": [],
        }
        bar = render_card._diff_bar(no_change_diff, has_prev=True)
        assert "No package changes" in bar


# ── _build_html ───────────────────────────────────────────────────────────────

class TestBuildHtml:
    def _build(self, versions=None, **kwargs):
        if versions is None:
            versions = VERSIONS_NO_PREV
        defaults = dict(
            tag="2026-05-14-abc1234",
            date="2026-05-14",
            sha7="abc1234",
            project_name="Bluefin",
            accent_color="#0ea5e9",
            badge_label="Stable",
            image_ref="ghcr.io/projectbluefin/bluefin",
            docs_url="https://docs.projectbluefin.io/changelogs",
        )
        defaults.update(kwargs)
        return render_card._build_html(versions, **defaults)

    def test_returns_html_string(self):
        html = self._build()
        assert html.startswith("<!DOCTYPE html>")

    def test_project_name_injected(self):
        html = self._build(project_name="Bluefin")
        assert "Bluefin" in html

    def test_accent_color_injected(self):
        html = self._build(accent_color="#ff0000")
        assert "#ff0000" in html

    def test_badge_label_injected(self):
        html = self._build(badge_label="Stable")
        assert "Stable" in html

    def test_tag_injected(self):
        html = self._build(tag="2026-05-14-abc1234")
        assert "2026-05-14" in html

    def test_kernel_chip_present(self):
        html = self._build()
        assert "Kernel" in html
        assert "6.10.0" in html

    def test_with_prev_shows_diff_bar(self):
        html = self._build(versions=VERSIONS_WITH_PREV)
        assert "updated" in html

    def test_html_escaping_project_name(self):
        html = self._build(project_name="<Test>")
        assert "<Test>" not in html
        assert "&lt;Test&gt;" in html
