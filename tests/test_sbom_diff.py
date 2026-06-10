"""
Unit tests for sbom_diff.py — SPDX 2.3 SBOM parsing and diff generation.
"""
import json
import os
import pytest
from pathlib import Path

import sbom_diff

FIXTURES = Path(__file__).parent / "fixtures"
CURRENT_SBOM  = str(FIXTURES / "current.spdx.json")
PREVIOUS_SBOM = str(FIXTURES / "previous.spdx.json")
NOTABLE_JSON  = str(FIXTURES / "notable.json")


# ── clean_version ─────────────────────────────────────────────────────────────

class TestCleanVersion:
    def test_strips_epoch(self):
        assert sbom_diff.clean_version("2:1.2.3") == "1.2.3"

    def test_strips_fc_release(self):
        assert sbom_diff.clean_version("6.10.0.fc40") == "6.10.0"

    def test_strips_epoch_and_fc(self):
        assert sbom_diff.clean_version("1:5.2.0.fc41") == "5.2.0"

    def test_plain_version_unchanged(self):
        assert sbom_diff.clean_version("47.1") == "47.1"

    def test_none_returns_none(self):
        assert sbom_diff.clean_version(None) is None

    def test_empty_string_returns_none(self):
        assert sbom_diff.clean_version("") is None


# ── short_sha ─────────────────────────────────────────────────────────────────

class TestShortSha:
    def test_40_char_hex_returns_first_8(self):
        sha = "a" * 40
        assert sbom_diff.short_sha(sha) == "a" * 8

    def test_64_char_hex(self):
        sha = "b" * 64
        assert sbom_diff.short_sha(sha) == "b" * 8

    def test_non_hex_returns_none(self):
        assert sbom_diff.short_sha("1.2.3") is None

    def test_none_returns_none(self):
        assert sbom_diff.short_sha(None) is None


# ── best_version ──────────────────────────────────────────────────────────────

class TestBestVersion:
    def test_semver_returned(self):
        assert sbom_diff.best_version("6.10.0") == "6.10.0"

    def test_epoch_stripped(self):
        assert sbom_diff.best_version("2:6.10.0") == "6.10.0"

    def test_full_sha_returned_as_is(self):
        # best_version passes the SHA through clean_version (which returns it unchanged),
        # then returns it. short_sha() is only called when clean_version returns None.
        sha = "deadbeef" * 5  # 40-char hex
        result = sbom_diff.best_version(sha)
        assert result == sha

    def test_none_returns_none(self):
        assert sbom_diff.best_version(None) is None


# ── is_semver ─────────────────────────────────────────────────────────────────

class TestIsSemver:
    def test_valid_semver(self):
        assert sbom_diff.is_semver("6.10.0") is True
        assert sbom_diff.is_semver("47.1") is True

    def test_sha_not_semver(self):
        assert sbom_diff.is_semver("a" * 8) is False

    def test_none_not_semver(self):
        assert sbom_diff.is_semver(None) is False

    def test_empty_not_semver(self):
        assert sbom_diff.is_semver("") is False


# ── load_pkg_map ──────────────────────────────────────────────────────────────

class TestLoadPkgMap:
    def test_loads_packages_from_fixture(self):
        pkg_map = sbom_diff.load_pkg_map(CURRENT_SBOM)
        assert "linux" in pkg_map
        assert "gnome-shell" in pkg_map
        assert "firefox" in pkg_map

    def test_version_extracted(self):
        pkg_map = sbom_diff.load_pkg_map(CURRENT_SBOM)
        assert pkg_map["linux"]["ver"] == "6.10.0"
        assert pkg_map["firefox"]["ver"] == "131.0"

    def test_previous_sbom(self):
        pkg_map = sbom_diff.load_pkg_map(PREVIOUS_SBOM)
        assert pkg_map["linux"]["ver"] == "6.9.14"


# ── count_packages ────────────────────────────────────────────────────────────

class TestCountPackages:
    def test_count_current(self):
        count = sbom_diff.count_packages(CURRENT_SBOM)
        assert count == 5  # matches fixture

    def test_count_previous(self):
        count = sbom_diff.count_packages(PREVIOUS_SBOM)
        assert count == 4


# ── extract_notable ───────────────────────────────────────────────────────────

class TestExtractNotable:
    def test_extracts_notable_packages(self):
        curr = sbom_diff.load_pkg_map(CURRENT_SBOM)
        notable_spec = json.loads(Path(NOTABLE_JSON).read_text())
        result = sbom_diff.extract_notable(curr, None, notable_spec)
        names = [n["name"] for n in result]
        assert "Kernel" in names
        assert "GNOME Shell" in names
        assert "Firefox" in names

    def test_no_prev_changed_false(self):
        curr = sbom_diff.load_pkg_map(CURRENT_SBOM)
        notable_spec = json.loads(Path(NOTABLE_JSON).read_text())
        result = sbom_diff.extract_notable(curr, None, notable_spec)
        for n in result:
            assert n["changed"] is False

    def test_with_prev_marks_changed(self):
        curr = sbom_diff.load_pkg_map(CURRENT_SBOM)
        prev = sbom_diff.load_pkg_map(PREVIOUS_SBOM)
        notable_spec = json.loads(Path(NOTABLE_JSON).read_text())
        result = sbom_diff.extract_notable(curr, prev, notable_spec)
        kernel = next(n for n in result if n["name"] == "Kernel")
        assert kernel["changed"] is True
        assert kernel["prev"] == "6.9.14"
        assert kernel["version"] == "6.10.0"

    def test_firefox_unchanged(self):
        curr = sbom_diff.load_pkg_map(CURRENT_SBOM)
        prev = sbom_diff.load_pkg_map(PREVIOUS_SBOM)
        notable_spec = json.loads(Path(NOTABLE_JSON).read_text())
        result = sbom_diff.extract_notable(curr, prev, notable_spec)
        firefox = next(n for n in result if n["name"] == "Firefox")
        assert firefox["changed"] is False


# ── diff_sboms ────────────────────────────────────────────────────────────────

class TestDiffSboms:
    def _get_diff(self):
        curr = sbom_diff.load_pkg_map(CURRENT_SBOM)
        prev = sbom_diff.load_pkg_map(PREVIOUS_SBOM)
        return sbom_diff.diff_sboms(curr, prev)

    def test_changed_packages(self):
        diff = self._get_diff()
        changed_names = {c["name"] for c in diff["changed"]}
        assert "linux" in changed_names
        assert "gnome-shell" in changed_names

    def test_added_packages(self):
        diff = self._get_diff()
        added_names = {a["name"] for a in diff["added"]}
        assert "podman" in added_names
        assert "new-package" in added_names

    def test_removed_packages(self):
        diff = self._get_diff()
        removed_names = {r["name"] for r in diff["removed"]}
        assert "old-package" in removed_names

    def test_unchanged_package_not_in_diff(self):
        diff = self._get_diff()
        changed_names = {c["name"] for c in diff["changed"]}
        assert "firefox" not in changed_names

    def test_counts_are_correct(self):
        diff = self._get_diff()
        assert diff["changed_count"] == len(diff["changed"])
        assert diff["added_count"] == len(diff["added"])
        assert diff["removed_count"] == len(diff["removed"])

    def test_empty_diff_when_identical(self):
        curr = sbom_diff.load_pkg_map(CURRENT_SBOM)
        diff = sbom_diff.diff_sboms(curr, curr)
        assert diff["changed_count"] == 0
        assert diff["added_count"] == 0
        assert diff["removed_count"] == 0
