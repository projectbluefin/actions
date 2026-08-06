"""Regression coverage for implementation-time self-repository references."""
from pathlib import Path

import importlib.util


SCRIPT = Path(__file__).parent.parent / "scripts" / "check-self-repository-references.py"
spec = importlib.util.spec_from_file_location("check_self_repository_references", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_repository_has_no_invalid_self_references():
    assert module.find_invalid_references() == []


def test_checker_allows_external_and_self_repository_syntax(tmp_path, monkeypatch):
    (tmp_path / ".github").mkdir()
    workflow = tmp_path / ".github" / "workflow.yml"
    workflow.write_text(
        """
uses: $/bootc-build/push-image
uses: actions/checkout@abc123
# uses: projectbluefin/actions/bootc-build/push-image@v1
"""
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SEARCH_ROOTS", (tmp_path / ".github",))
    assert module.find_invalid_references() == []


def test_checker_rejects_qualified_and_workspace_relative_self_references(tmp_path, monkeypatch):
    (tmp_path / ".github").mkdir()
    workflow = tmp_path / ".github" / "workflow.yml"
    workflow.write_text(
        """
uses: projectbluefin/actions/bootc-build/push-image@v1
uses: ./bootc-build/push-image
"""
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SEARCH_ROOTS", (tmp_path / ".github",))
    failures = module.find_invalid_references()
    assert len(failures) == 2
