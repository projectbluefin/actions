"""
Entry-point (main()) tests for render_notes, sbom_diff, and check-consumer-contract.
These tests target the CLI entry points to cover lines 308-369 in render_notes,
lines 184-238 in sbom_diff, and lines 96-139 in check-consumer-contract.
"""

from __future__ import annotations

import json
import sys
import importlib.util
import pytest
from pathlib import Path

# Conftest adds create-release/scripts and scripts to sys.path
import render_notes
import sbom_diff

_SCRIPT = Path(__file__).parent.parent / "scripts" / "check-consumer-contract.py"
_spec = importlib.util.spec_from_file_location("check_consumer_contract", _SCRIPT)
_ccc_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ccc_mod)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def current_sbom(tmp_path):
    sbom = {
        "packages": [
            {"name": "bash", "versionInfo": "5.2", "SPDXID": "SPDXRef-bash"},
            {"name": "curl", "versionInfo": "8.0", "SPDXID": "SPDXRef-curl"},
        ]
    }
    p = tmp_path / "current.spdx.json"
    p.write_text(json.dumps(sbom))
    return str(p)


@pytest.fixture()
def previous_sbom(tmp_path):
    sbom = {
        "packages": [
            {"name": "bash", "versionInfo": "5.1", "SPDXID": "SPDXRef-bash"},
            {"name": "curl", "versionInfo": "7.9", "SPDXID": "SPDXRef-curl"},
        ]
    }
    p = tmp_path / "previous.spdx.json"
    p.write_text(json.dumps(sbom))
    return str(p)


@pytest.fixture()
def notable_spec_file(tmp_path):
    spec = [{"sbom_name": "bash", "label": "Bash"}]
    p = tmp_path / "notable.json"
    p.write_text(json.dumps(spec))
    return str(p)


@pytest.fixture()
def versions_json(tmp_path, current_sbom, previous_sbom, notable_spec_file):
    """Run sbom_diff.main() to produce a versions.json for render_notes.main()."""
    out = tmp_path / "versions.json"
    sys.argv = [
        "sbom_diff.py",
        "--current", current_sbom,
        "--previous", previous_sbom,
        "--notable-packages", notable_spec_file,
        "--output", str(out),
    ]
    sbom_diff.main()
    return str(out)


# ── sbom_diff.main() ──────────────────────────────────────────────────────────

class TestSbomDiffMain:
    def test_produces_output_json(self, tmp_path, current_sbom, previous_sbom, notable_spec_file):
        out = tmp_path / "versions.json"
        sys.argv = [
            "sbom_diff.py",
            "--current", current_sbom,
            "--previous", previous_sbom,
            "--notable-packages", notable_spec_file,
            "--output", str(out),
        ]
        sbom_diff.main()
        assert out.exists()
        data = json.loads(out.read_text())
        assert "diff" in data
        assert "notable" in data
        assert "has_prev" in data
        assert data["has_prev"] is True

    def test_no_previous_sbom(self, tmp_path, current_sbom, notable_spec_file):
        out = tmp_path / "versions.json"
        sys.argv = [
            "sbom_diff.py",
            "--current", current_sbom,
            "--notable-packages", notable_spec_file,
            "--output", str(out),
        ]
        sbom_diff.main()
        data = json.loads(out.read_text())
        assert data["has_prev"] is False

    def test_missing_current_exits(self, tmp_path, notable_spec_file):
        out = tmp_path / "versions.json"
        sys.argv = [
            "sbom_diff.py",
            "--current", "/nonexistent/sbom.json",
            "--notable-packages", notable_spec_file,
            "--output", str(out),
        ]
        with pytest.raises(SystemExit) as exc:
            sbom_diff.main()
        assert exc.value.code != 0


# ── render_notes.main() ───────────────────────────────────────────────────────

class TestRenderNotesMain:
    def test_produces_release_notes_md(self, tmp_path, versions_json, current_sbom):
        out = tmp_path / "release-notes.md"
        sys.argv = [
            "render_notes.py",
            "--versions", versions_json,
            "--sbom", current_sbom,
            "--tag", "v42.20250531",
            "--title", "Bluefin 42.20250531",
            "--image", "ghcr.io/projectbluefin/bluefin",
            "--digest", "sha256:abc123",
            "--repo", "projectbluefin/bluefin",
            "--cert-regexp", "https://github.com/projectbluefin/bluefin/.*",
            "--output", str(out),
        ]
        render_notes.main()
        assert out.exists()
        content = out.read_text()
        assert "bluefin" in content.lower()
        assert "## Desktop Screenshot" in content
        assert "https://projectbluefin.github.io/testsuite/screenshots/bluefin-testing-smoke-latest.png" in content

    def test_missing_versions_file_exits(self, tmp_path, current_sbom):
        out = tmp_path / "release-notes.md"
        sys.argv = [
            "render_notes.py",
            "--versions", "/nonexistent/versions.json",
            "--sbom", current_sbom,
            "--tag", "v42",
            "--title", "Test",
            "--image", "ghcr.io/test",
            "--digest", "sha256:abc",
            "--repo", "org/repo",
            "--cert-regexp", ".*",
            "--output", str(out),
        ]
        with pytest.raises(SystemExit) as exc:
            render_notes.main()
        assert exc.value.code != 0

    def test_sbom_filename_defaults_to_basename(self, tmp_path, versions_json, current_sbom):
        out = tmp_path / "release-notes.md"
        sys.argv = [
            "render_notes.py",
            "--versions", versions_json,
            "--sbom", current_sbom,
            "--tag", "v42",
            "--title", "Test",
            "--image", "ghcr.io/test",
            "--digest", "sha256:abc",
            "--repo", "org/repo",
            "--cert-regexp", ".*",
            "--output", str(out),
        ]
        render_notes.main()
        # Should succeed without --sbom-filename
        assert out.exists()


# ── check-consumer-contract.main() ───────────────────────────────────────────

class TestCheckConsumerContractMain:
    def test_passes_with_real_contract_file(self, monkeypatch):
        """Smoke test: main() with the real consumer-contract.yml should pass."""
        monkeypatch.setattr(sys, "argv", ["check-consumer-contract.py"])
        result = _ccc_mod.main()
        assert result == 0

    def test_fails_when_contract_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_ccc_mod, "CONTRACT_FILE", tmp_path / "missing.yml")
        monkeypatch.setattr(sys, "argv", ["check-consumer-contract.py"])
        result = _ccc_mod.main()
        assert result == 1

    def test_verbose_mode(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["check-consumer-contract.py", "--verbose"])
        result = _ccc_mod.main()
        assert result == 0
