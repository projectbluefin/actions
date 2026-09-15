"""Tests for scripts/validate_thin_caller.py."""
import sys
from pathlib import Path
import pytest

from scripts.validate_thin_caller import (
    count_effective_lines,
    file_uses_projectbluefin,
    find_workflows,
    main,
)


def test_count_effective_lines(tmp_path):
    f = tmp_path / "workflow.yml"
    f.write_text("""# Comment line
name: Build

on:
  push:
    branches: [main] # inline comment

# Another comment
jobs:
  build:
    runs-on: ubuntu-latest
""")
    # Total lines: 12. Empty/blank: 3. Comment lines: 2. Effective: 7.
    assert count_effective_lines(f) == 7


def test_file_uses_projectbluefin(tmp_path):
    f1 = tmp_path / "uses_actions.yml"
    f1.write_text("uses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1\n")
    assert file_uses_projectbluefin(f1) is True

    f2 = tmp_path / "no_actions.yml"
    f2.write_text("uses: actions/checkout@v4\n")
    assert file_uses_projectbluefin(f2) is False


def test_file_uses_projectbluefin_ignores_comments(tmp_path):
    # A commented-out reference is documentation, not a caller.
    f = tmp_path / "doc.yml"
    f.write_text("# uses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1\nname: Doc\n")
    assert file_uses_projectbluefin(f) is False

    # Active reference after a comment line counts as a caller.
    f2 = tmp_path / "caller.yml"
    f2.write_text("# pinned-ref example\nuses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1\n")
    assert file_uses_projectbluefin(f2) is True


def test_find_workflows(tmp_path):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "build.yml").write_text("name: Build\n")
    (wf_dir / "release.yaml").write_text("name: Release\n")
    (wf_dir / "other.txt").write_text("not a workflow\n")

    found = find_workflows(tmp_path)
    assert len(found) == 2
    assert str(wf_dir / "build.yml") in found
    assert str(wf_dir / "release.yaml") in found


def test_main_with_violations(tmp_path, monkeypatch):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    caller = wf_dir / "caller.yml"
    lines = ["name: Caller\n", "uses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1\n"]
    # Add enough lines to exceed max-lines=5
    lines.extend([f"key_{i}: value_{i}\n" for i in range(10)])
    caller.write_text("".join(lines))

    monkeypatch.setattr(sys, "argv", ["validate_thin_caller.py", "--root", str(tmp_path), "--max-lines", "5"])
    assert main() == 1


def test_main_passes_within_limit(tmp_path, monkeypatch):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    caller = wf_dir / "caller.yml"
    caller.write_text("name: Caller\nuses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1\n")

    monkeypatch.setattr(sys, "argv", ["validate_thin_caller.py", "--root", str(tmp_path), "--max-lines", "50"])
    assert main() == 0
