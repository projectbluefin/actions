"""
Unit tests for check-consumer-contract.py — consumer input contract validation.

The script uses REPO_ROOT to locate live action files, so we either:
  a) Point tests at the real repo files (integration-style), or
  b) Use tmp_path fixtures to create synthetic action YAML files.

We do both: fast pure-unit tests for get_live_inputs / check_contract,
plus a smoke test against the real consumer-contract.yml.
"""
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

# Load the module (filename has a dash, cannot use regular import)
_SCRIPT = Path(__file__).parent.parent / "scripts" / "check-consumer-contract.py"
_spec = importlib.util.spec_from_file_location("check_consumer_contract", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

get_live_inputs = _mod.get_live_inputs
check_contract  = _mod.check_contract


# ── get_live_inputs ───────────────────────────────────────────────────────────

class TestGetLiveInputs:
    def test_reads_composite_action_inputs(self, tmp_path):
        action_yml = tmp_path / "action.yml"
        action_yml.write_text("""
name: test-action
inputs:
  image-name:
    description: "Image name"
    required: true
  tag:
    description: "Tag"
runs:
  using: composite
  steps: []
""")
        inputs = get_live_inputs(action_yml)
        assert "image-name" in inputs
        assert "tag" in inputs

    def test_reads_reusable_workflow_inputs(self, tmp_path):
        wf_yml = tmp_path / "reusable.yml"
        wf_yml.write_text("""
on:
  workflow_call:
    inputs:
      stream_name:
        type: string
        required: true
      brand_name:
        type: string
jobs: {}
""")
        inputs = get_live_inputs(wf_yml)
        assert "stream_name" in inputs
        assert "brand_name" in inputs

    def test_missing_file_returns_empty_set(self, tmp_path):
        inputs = get_live_inputs(tmp_path / "nonexistent.yml")
        assert inputs == set()

    def test_empty_action_returns_empty_set(self, tmp_path):
        action_yml = tmp_path / "action.yml"
        action_yml.write_text("name: empty\nruns:\n  using: composite\n  steps: []\n")
        inputs = get_live_inputs(action_yml)
        assert inputs == set()


# ── check_contract ────────────────────────────────────────────────────────────

class TestCheckContract:
    def _make_action(self, tmp_path: Path, name: str, inputs: list[str]) -> Path:
        """Write a minimal composite action YAML with the given input names."""
        d = tmp_path / "bootc-build" / name
        d.mkdir(parents=True)
        p = d / "action.yml"
        inputs_block = "\n".join(
            f"  {i}:\n    description: '{i}'\n    required: false"
            for i in inputs
        )
        p.write_text(f"name: {name}\ninputs:\n{inputs_block}\nruns:\n  using: composite\n  steps: []\n")
        return p

    def _make_workflow(self, tmp_path: Path, inputs: list[str]) -> Path:
        """Write a minimal reusable workflow YAML with the given input names."""
        d = tmp_path / ".github" / "workflows"
        d.mkdir(parents=True)
        p = d / "reusable-build.yml"
        inputs_block = "\n".join(
            f"      {i}:\n        type: string\n        required: false"
            for i in inputs
        )
        p.write_text(f"on:\n  workflow_call:\n    inputs:\n{inputs_block}\njobs: {{}}\n")
        return p

    def test_passes_when_required_inputs_present(self, tmp_path, monkeypatch):
        self._make_workflow(tmp_path, ["stream_name", "brand_name"])
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        contract = {
            "reusable_workflow": {
                "path": ".github/workflows/reusable-build.yml",
                "required_inputs": ["stream_name"],
            }
        }
        failures = check_contract(contract, verbose=False)
        assert failures == []

    def test_fails_when_required_input_missing(self, tmp_path, monkeypatch):
        self._make_workflow(tmp_path, ["brand_name"])  # stream_name is missing
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        contract = {
            "reusable_workflow": {
                "path": ".github/workflows/reusable-build.yml",
                "required_inputs": ["stream_name"],
            }
        }
        failures = check_contract(contract, verbose=False)
        assert len(failures) == 1
        assert "stream_name" in failures[0]

    def test_fails_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        contract = {
            "reusable_workflow": {
                "path": ".github/workflows/nonexistent.yml",
                "required_inputs": ["stream_name"],
            }
        }
        failures = check_contract(contract, verbose=False)
        assert len(failures) == 1
        assert "missing" in failures[0]

    def test_composite_action_passes(self, tmp_path, monkeypatch):
        self._make_action(tmp_path, "setup-runner", ["storage-backend"])
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        contract = {
            "composite_actions": {
                "setup-runner": {
                    "path": "bootc-build/setup-runner/action.yml",
                    "required_inputs": ["storage-backend"],
                }
            }
        }
        failures = check_contract(contract, verbose=False)
        assert failures == []

    def test_composite_action_fails_on_missing_input(self, tmp_path, monkeypatch):
        self._make_action(tmp_path, "setup-runner", ["other-input"])
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        contract = {
            "composite_actions": {
                "setup-runner": {
                    "path": "bootc-build/setup-runner/action.yml",
                    "required_inputs": ["storage-backend"],
                }
            }
        }
        failures = check_contract(contract, verbose=False)
        assert len(failures) == 1
        assert "storage-backend" in failures[0]

    def test_empty_contract_returns_no_failures(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
        failures = check_contract({}, verbose=False)
        assert failures == []


# ── Smoke test against real repo ──────────────────────────────────────────────

class TestRealContract:
    """Smoke test: the real consumer-contract.yml must pass against live action files."""

    def test_real_contract_passes(self):
        """Run check_contract against the actual repo files — no regressions allowed."""
        contract_path = _mod.CONTRACT_FILE
        if not contract_path.exists():
            pytest.skip("consumer-contract.yml not found — skipping real-repo smoke test")
        with open(contract_path) as f:
            contract = yaml.safe_load(f) or {}
        failures = check_contract(contract, verbose=False)
        assert failures == [], f"Consumer contract violations:\n" + "\n".join(failures)
