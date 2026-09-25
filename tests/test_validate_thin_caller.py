"""Tests for scripts/validate_thin_caller.py."""
import sys
from pathlib import Path
import pytest

from scripts.validate_thin_caller import (
    count_effective_lines,
    file_uses_projectbluefin,
    find_reusable_workflows,
    find_workflows,
    get_reusable_requires_annotation,
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

    # A composite-action reference (bootc-build/*) is not a reusable-workflow
    # delegation — it's a step among other logic, not a thin pointer, and
    # consumer repos like bluefin have long, legitimately-sized workflows
    # built this way (issue #546).
    f3 = tmp_path / "composite_action.yml"
    f3.write_text("uses: projectbluefin/actions/bootc-build/validate-pr@v1\n")
    assert file_uses_projectbluefin(f3) is False

    # A commented-out reference is documentation, not a caller (issue #546).
    f4 = tmp_path / "commented.yml"
    f4.write_text("#   uses: projectbluefin/actions/.github/workflows/reusable-build.yml@v1\nname: x\n")
    assert file_uses_projectbluefin(f4) is False


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


def test_get_reusable_requires_annotation(tmp_path):
    f_any = tmp_path / "reusable-test.yml"
    f_any.write_text("""name: Test
on:
  workflow_call:
    # requires: any
    inputs:
      test:
        type: string
""")
    assert get_reusable_requires_annotation(f_any) == "any"

    f_app = tmp_path / "reusable-app.yml"
    f_app.write_text("""name: App
on:
  workflow_call:
    # requires: App-token
""")
    assert get_reusable_requires_annotation(f_app) == "App-token"

    f_combo = tmp_path / "reusable-combo.yml"
    f_combo.write_text("""name: Combo
on:
  workflow_call:
    # requires: PAT|App-token
""")
    assert get_reusable_requires_annotation(f_combo) == "PAT|App-token"

    f_all = tmp_path / "reusable-all.yml"
    f_all.write_text("""name: All
on:
  workflow_call:
    # requires: PAT|App-token|any
""")
    assert get_reusable_requires_annotation(f_all) == "PAT|App-token|any"

    f_invalid = tmp_path / "reusable-invalid.yml"
    f_invalid.write_text("""name: Invalid
on:
  workflow_call:
    # requires: invalid-token-type
""")
    assert get_reusable_requires_annotation(f_invalid) is None

    f_missing = tmp_path / "reusable-missing.yml"
    f_missing.write_text("""name: Missing
on:
  workflow_call:
    inputs:
      foo:
        type: string
""")
    assert get_reusable_requires_annotation(f_missing) is None


def test_find_reusable_workflows(tmp_path):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "reusable-build.yml").write_text("name: Build\n")
    (wf_dir / "reusable-release.yaml").write_text("name: Release\n")
    (wf_dir / "caller.yml").write_text("name: Caller\n")

    reusables = find_reusable_workflows(tmp_path)
    assert len(reusables) == 2
    assert str(wf_dir / "reusable-build.yml") in reusables
    assert str(wf_dir / "reusable-release.yaml") in reusables


def test_main_check_reusable_requires_flag(tmp_path, monkeypatch):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)

    # Empty
    monkeypatch.setattr(
        sys,
        "argv",
        ["validate_thin_caller.py", "--root", str(tmp_path), "--check-reusable-requires"],
    )
    assert main() == 0

    # Valid reusable workflow
    reusable = wf_dir / "reusable-valid.yml"
    reusable.write_text("on:\n  workflow_call:\n    # requires: any\n")
    assert main() == 0

    # Missing annotation
    reusable_bad = wf_dir / "reusable-bad.yml"
    reusable_bad.write_text("on:\n  workflow_call:\n    inputs:\n")
    assert main() == 1


def test_live_reusable_workflows_have_valid_token_annotations():
    repo_root = Path(__file__).resolve().parent.parent
    reusables = find_reusable_workflows(repo_root)
    assert len(reusables) > 0

    for wf in reusables:
        annotation = get_reusable_requires_annotation(wf)
        assert annotation is not None, (
            f"{Path(wf).name} is missing a valid '# requires: PAT|App-token|any' annotation under workflow_call:"
        )

