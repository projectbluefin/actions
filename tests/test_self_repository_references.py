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


def _stub_root(tmp_path, monkeypatch, contents: str):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "workflow.yml").write_text(contents)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SEARCH_ROOTS", (tmp_path / ".github",))


def test_main_returns_zero_and_reports_success(tmp_path, monkeypatch, capsys):
    _stub_root(tmp_path, monkeypatch, "uses: $/bootc-build/push-image\n")
    assert module.main() == 0
    assert "Self-repository references use $/." in capsys.readouterr().out


def test_main_returns_one_and_prints_each_failure(tmp_path, monkeypatch, capsys):
    _stub_root(
        tmp_path,
        monkeypatch,
        "uses: projectbluefin/actions/bootc-build/push-image@v1\nuses: ./bootc-build/push-image\n",
    )
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "Invalid caller-workspace self references found:" in out
    assert "workflow.yml:1:" in out
    assert "workflow.yml:2:" in out


def test_workflow_files_collects_yml_and_yaml_sorted(tmp_path, monkeypatch):
    root = tmp_path / ".github"
    (root / "nested").mkdir(parents=True)
    (root / "b.yaml").write_text("")
    (root / "a.yml").write_text("")
    (root / "nested" / "c.yml").write_text("")
    monkeypatch.setattr(module, "SEARCH_ROOTS", (root,))
    assert [p.name for p in module.workflow_files()] == ["a.yml", "b.yaml", "c.yml"]


def test_workflow_files_skips_non_yaml_and_directories(tmp_path, monkeypatch):
    root = tmp_path / ".github"
    (root / "dir.yml").mkdir(parents=True)
    (root / "notes.md").write_text("uses: ./bootc-build/push-image")
    (root / "script.sh").write_text("")
    monkeypatch.setattr(module, "SEARCH_ROOTS", (root,))
    assert module.workflow_files() == []


def test_workflow_files_excludes_agent_worktree_paths(tmp_path, monkeypatch):
    root = tmp_path / ".github"
    (root / "quality-work").mkdir(parents=True)
    (root / "scanner-worktree").mkdir()
    (root / "quality-work" / "shadow.yml").write_text("uses: ./bootc-build/push-image")
    (root / "scanner-worktree" / "shadow.yml").write_text("uses: ./bootc-build/push-image")
    (root / "real.yml").write_text("uses: $/bootc-build/push-image")
    monkeypatch.setattr(module, "SEARCH_ROOTS", (root,))
    assert [p.name for p in module.workflow_files()] == ["real.yml"]


def test_find_invalid_references_ignores_indented_comment_lines(tmp_path, monkeypatch):
    _stub_root(tmp_path, monkeypatch, "  # uses: ./bootc-build/push-image\n  uses: ./real\n")
    failures = module.find_invalid_references()
    assert len(failures) == 1
    assert failures[0].endswith("uses: ./real")
