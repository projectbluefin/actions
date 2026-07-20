"""
Additional tests to boost coverage for render_notes and sbom_diff scripts.

Targets currently uncovered paths:
- render_notes._md_table (lines 41-44)
- render_notes._section_card (lines 69-70)
- sbom_diff.load_pkg_map with name-deduplication paths (line 93)
- sbom_diff.extract_notable with spdxid_filter (lines 125, 132)

Note: _load_full_inventory and _section_full_inventory were removed from
render_notes in b1ac15b (the full SPDX package table was dropped from release
notes). The duplicate tests for those functions live here and are deleted.
"""

from __future__ import annotations

import json
import textwrap
import pytest
from pathlib import Path


# ── render_notes helpers ──────────────────────────────────────────────────────

# conftest.py already adds create-release/scripts to sys.path
import render_notes


class TestMdTable:
    """Tests for render_notes._md_table (lines 41-44)."""

    def test_single_row(self):
        result = render_notes._md_table(["A", "B"], [["val1", "val2"]])
        assert "| A | B |" in result
        assert "| --- | --- |" in result
        assert "val1" in result
        assert "val2" in result

    def test_multiple_rows(self):
        rows = [["a", "1"], ["b", "2"], ["c", "3"]]
        result = render_notes._md_table(["Name", "Version"], rows)
        lines = result.split("\n")
        # Header + separator + 3 data rows
        assert len(lines) >= 5
        assert "Name" in lines[0]

    def test_single_column(self):
        result = render_notes._md_table(["Package"], [["bash"], ["curl"]])
        assert "Package" in result
        assert "bash" in result
        assert "curl" in result

    def test_empty_rows(self):
        result = render_notes._md_table(["A", "B"], [])
        assert "| A | B |" in result
        assert "| --- | --- |" in result


class TestSectionCard:
    """Tests for render_notes._section_card (lines 69-70)."""

    def test_renders_image_link(self):
        result = render_notes._section_card("v42.20250531", "projectbluefin/bluefin")
        assert "![Release card]" in result
        assert "projectbluefin/bluefin" in result
        assert "v42.20250531" in result
        assert "release-card.png" in result


# ── sbom_diff additional coverage ────────────────────────────────────────────

import sbom_diff as sd


class TestLoadPkgMapDeduplication:
    """Tests for load_pkg_map with name deduplication (line 93)."""

    def _write_sbom(self, tmp_path: Path, packages: list[dict]) -> str:
        sbom = {"packages": packages}
        p = tmp_path / "sbom.spdx.json"
        p.write_text(json.dumps(sbom))
        return str(p)

    def test_skips_packages_without_name(self, tmp_path):
        path = self._write_sbom(tmp_path, [
            {"name": "", "versionInfo": "1.0", "SPDXID": "SPDXRef-empty"},
            {"name": "curl", "versionInfo": "8.0", "SPDXID": "SPDXRef-curl"},
        ])
        result = sd.load_pkg_map(path)
        assert "" not in result
        assert "curl" in result

    def test_multiple_entries_per_package_kept_best(self, tmp_path):
        # Same package name with semver and non-semver versions
        path = self._write_sbom(tmp_path, [
            {"name": "bash", "versionInfo": "not-semver", "SPDXID": "SPDXRef-1"},
            {"name": "bash", "versionInfo": "5.2.0", "SPDXID": "SPDXRef-2"},
        ])
        result = sd.load_pkg_map(path)
        assert "bash" in result
        # Semver version should win
        assert result["bash"]["ver"] == "5.2.0"


class TestExtractNotableWithSpdxFilter:
    """Tests for extract_notable with spdxid_filter (lines 125, 132)."""

    def _curr_map(self):
        return {
            "linux": {"ver": "6.14.9", "raw": "6.14.9", "spdxid": "SPDXRef-linux-kernel"},
            "bash":  {"ver": "5.2",    "raw": "5.2",    "spdxid": "SPDXRef-bash"},
        }

    def test_spdxid_filter_matches_selects_package(self):
        spec = [{"sbom_name": "linux", "label": "Linux kernel", "spdxid_filter": "kernel"}]
        result = sd.extract_notable(self._curr_map(), None, spec)
        names = [r["name"] for r in result]
        assert "Linux kernel" in names

    def test_spdxid_filter_mismatch_skips_package(self):
        # Filter "xattr" doesn't appear in linux's SPDXID
        spec = [{"sbom_name": "linux", "label": "Linux kernel", "spdxid_filter": "xattr"}]
        result = sd.extract_notable(self._curr_map(), None, spec)
        assert result == []

    def test_no_spdxid_filter_includes_package(self):
        spec = [{"sbom_name": "bash", "label": "Bash"}]
        result = sd.extract_notable(self._curr_map(), None, spec)
        names = [r["name"] for r in result]
        assert "Bash" in names

    def test_package_not_in_curr_map_skipped(self):
        spec = [{"sbom_name": "nonexistent"}]
        result = sd.extract_notable(self._curr_map(), None, spec)
        assert result == []


# ── check-consumer-contract additional coverage ───────────────────────────────

import importlib.util
from pathlib import Path as _Path

_SCRIPT = _Path(__file__).parent.parent / "scripts" / "check-consumer-contract.py"
_spec = importlib.util.spec_from_file_location("check_consumer_contract", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
check_contract = _mod.check_contract
get_live_inputs = _mod.get_live_inputs


class TestCheckContractFileMissing:
    """Tests for check_contract when action files are missing (lines 60-62)."""

    def test_reports_failure_when_action_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        contract = {
            "composite_actions": {
                "my-action": {
                    "path": "actions/my-action/action.yml",
                    "required_inputs": ["image-name"],
                }
            }
        }
        failures = check_contract(contract, verbose=False)
        assert any("file missing" in f for f in failures)

    def test_verbose_mode_prints_warn_when_inputs_unparseable(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        # Create a file that exists but has no inputs section
        action_dir = tmp_path / "actions" / "my-action"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yml").write_text("name: test\nruns:\n  using: composite\n  steps: []\n")
        contract = {
            "composite_actions": {
                "my-action": {
                    "path": "actions/my-action/action.yml",
                    "required_inputs": [],
                }
            }
        }
        check_contract(contract, verbose=True)
        # Verbose mode should not error; we just verify it runs without exception

    def test_reports_missing_required_input(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        action_dir = tmp_path / "actions" / "my-action"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yml").write_text(
            "name: test\ninputs:\n  other-input:\n    description: x\nruns:\n  using: composite\n  steps: []\n"
        )
        contract = {
            "composite_actions": {
                "my-action": {
                    "path": "actions/my-action/action.yml",
                    "required_inputs": ["image-name"],
                }
            }
        }
        failures = check_contract(contract, verbose=False)
        assert any("image-name" in f for f in failures)

    def test_no_failures_when_all_inputs_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        action_dir = tmp_path / "actions" / "my-action"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yml").write_text(
            "name: test\ninputs:\n  image-name:\n    description: x\nruns:\n  using: composite\n  steps: []\n"
        )
        contract = {
            "composite_actions": {
                "my-action": {
                    "path": "actions/my-action/action.yml",
                    "required_inputs": ["image-name"],
                }
            }
        }
        failures = check_contract(contract, verbose=False)
        assert failures == []

    def test_verbose_ok_print(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        action_dir = tmp_path / "actions" / "my-action"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yml").write_text(
            "name: test\ninputs:\n  image-name:\n    description: x\nruns:\n  using: composite\n  steps: []\n"
        )
        contract = {
            "composite_actions": {
                "my-action": {
                    "path": "actions/my-action/action.yml",
                    "required_inputs": ["image-name"],
                }
            }
        }
        check_contract(contract, verbose=True)
        captured = capsys.readouterr()
        assert "OK" in captured.out
