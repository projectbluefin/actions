"""
Unit tests for render_notes.py — Markdown release notes generation.
"""
import pytest
import render_notes


# Shared fixture data
NOTABLE_NO_PREV = [
    {"name": "Kernel",     "version": "6.10.0", "prev": None,    "changed": False},
    {"name": "GNOME Shell","version": "47.1",   "prev": None,    "changed": False},
]

NOTABLE_WITH_PREV = [
    {"name": "Kernel",     "version": "6.10.0", "prev": "6.9.14","changed": True},
    {"name": "GNOME Shell","version": "47.1",   "prev": "47.0",  "changed": True},
    {"name": "Firefox",    "version": "131.0",  "prev": "131.0", "changed": False},
]

DIFF_EMPTY = {
    "changed_count": 0, "added_count": 0, "removed_count": 0,
    "changed": [], "added": [], "removed": [],
}

DIFF_FULL = {
    "changed_count": 2,
    "added_count":   1,
    "removed_count": 1,
    "changed": [
        {"name": "linux",      "prev": "6.9.14", "curr": "6.10.0"},
        {"name": "gnome-shell","prev": "47.0",   "curr": "47.1"},
    ],
    "added":   [{"name": "podman",      "version": "5.2.0"}],
    "removed": [{"name": "old-package", "version": "9.9.9"}],
}


# ── _section_notable ──────────────────────────────────────────────────────────

class TestSectionNotable:
    def test_contains_package_names(self):
        md = render_notes._section_notable(NOTABLE_NO_PREV)
        assert "Kernel" in md
        assert "GNOME Shell" in md

    def test_contains_versions(self):
        md = render_notes._section_notable(NOTABLE_NO_PREV)
        assert "6.10.0" in md
        assert "47.1" in md

    def test_changed_package_shows_prev(self):
        md = render_notes._section_notable(NOTABLE_WITH_PREV)
        assert "6.9.14" in md  # previous version for Kernel

    def test_empty_notable_produces_empty(self):
        md = render_notes._section_notable([])
        assert md == ""


# ── _section_diff_summary ─────────────────────────────────────────────────────

class TestSectionDiffSummary:
    def test_no_prev_shows_baseline_message(self):
        md = render_notes._section_diff_summary(DIFF_EMPTY, has_prev=False, total=100)
        assert "100" in md
        assert "No previous release baseline" in md

    def test_with_prev_shows_total(self):
        md = render_notes._section_diff_summary(DIFF_FULL, has_prev=True, total=423)
        assert "423" in md

    def test_with_prev_shows_changed_count(self):
        md = render_notes._section_diff_summary(DIFF_FULL, has_prev=True, total=423)
        assert "2" in md  # 2 changed

    def test_no_changes_still_generates_section(self):
        md = render_notes._section_diff_summary(DIFF_EMPTY, has_prev=True, total=100)
        assert md != ""
        assert "100" in md


# ── _section_diff_details ─────────────────────────────────────────────────────

class TestSectionDiffDetails:
    def test_no_prev_returns_empty(self):
        md = render_notes._section_diff_details(DIFF_FULL, has_prev=False)
        assert md == ""

    def test_changed_packages_appear(self):
        md = render_notes._section_diff_details(DIFF_FULL, has_prev=True)
        assert "linux" in md
        assert "gnome-shell" in md
        assert "6.9.14" in md
        assert "6.10.0" in md

    def test_added_packages_appear(self):
        md = render_notes._section_diff_details(DIFF_FULL, has_prev=True)
        assert "podman" in md
        assert "5.2.0" in md

    def test_removed_packages_appear(self):
        md = render_notes._section_diff_details(DIFF_FULL, has_prev=True)
        assert "old-package" in md

    def test_empty_diff_returns_empty(self):
        md = render_notes._section_diff_details(DIFF_EMPTY, has_prev=True)
        assert md == ""


# ── _section_supply_chain ─────────────────────────────────────────────────────

class TestSectionSupplyChain:
    def _call(self, **kwargs):
        defaults = dict(
            image="ghcr.io/projectbluefin/bluefin",
            digest="sha256:abc123def456",
            repo="projectbluefin/bluefin",
            tag="2026-05-14-abc1234",
            cert_regexp="^https://github\\.com/projectbluefin/",
            sbom_filename="bluefin.spdx.json",
            docs_url="https://docs.projectbluefin.io/changelogs",
        )
        defaults.update(kwargs)
        return render_notes._section_supply_chain(**defaults)

    def test_contains_image_reference(self):
        md = self._call()
        assert "ghcr.io/projectbluefin/bluefin" in md

    def test_contains_digest(self):
        md = self._call()
        assert "sha256:abc123def456" in md

    def test_contains_cosign_command(self):
        md = self._call()
        assert "cosign verify" in md

    def test_contains_oras_command(self):
        md = self._call()
        assert "oras discover" in md

    def test_contains_slsa_verifier(self):
        md = self._call()
        assert "slsa-verifier" in md

    def test_cert_regexp_injected(self):
        md = self._call(cert_regexp="^https://github.com/myorg/")
        assert "myorg" in md

    def test_sbom_filename_injected(self):
        md = self._call(sbom_filename="custom.spdx.json")
        assert "custom.spdx.json" in md
