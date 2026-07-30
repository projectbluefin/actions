"""Regression tests for Python script entrypoints.

These tests execute the modules as ``__main__`` entrypoints so the module guard
line is covered without relying on a full CLI invocation.
"""

from __future__ import annotations

import importlib.util
import os
import runpy
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_as_main(script_path: Path, *args: str) -> int | None:
    original_argv = sys.argv[:]
    original_cwd = Path.cwd()
    try:
        sys.argv = [str(script_path), *args]
        os.chdir(REPO_ROOT)
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(script_path), run_name="__main__")
        return excinfo.value.code
    finally:
        sys.argv = original_argv
        os.chdir(original_cwd)


def test_inject_xattrs_entrypoint_exits_for_bad_args():
    result = _run_as_main(REPO_ROOT / "bootc-build" / "chunka" / "inject-xattrs.py")
    assert result == 1


def test_render_notes_entrypoint_accepts_help():
    result = _run_as_main(REPO_ROOT / "bootc-build" / "create-release" / "scripts" / "render_notes.py", "--help")
    assert result == 0


def test_sbom_diff_entrypoint_accepts_help():
    result = _run_as_main(REPO_ROOT / "bootc-build" / "create-release" / "scripts" / "sbom_diff.py", "--help")
    assert result == 0


def test_render_gate_section_wrapper_writes_updated_body(tmp_path):
    module_path = REPO_ROOT / "scripts" / "render_gate_section.py"
    spec = importlib.util.spec_from_file_location("render_gate_section_wrapper", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    body_in = tmp_path / "body.md"
    body_out = tmp_path / "body-out.md"
    body_in.write_text(
        "<!-- gate-section-start -->\nold\n<!-- gate-section-end -->\n",
        encoding="utf-8",
    )

    original_argv = sys.argv[:]
    try:
        sys.argv = [
            "render_gate_section.py",
            "--body-file",
            str(body_in),
            "--output",
            str(body_out),
            "--resolve-ok",
            "true",
            "--resolve-summary",
            "ok",
            "--verify-ok",
            "true",
            "--verify-summary",
            "ok",
            "--e2e-state",
            "passed",
            "--e2e-summary",
            "done",
            "--ready",
            "true",
        ]
        module.main()
    finally:
        sys.argv = original_argv

    body = body_out.read_text(encoding="utf-8")
    assert "<!-- gate-section-start -->" in body
    assert "✅ All checks passed" in body


def test_render_pr_body_wrapper_writes_pr_body(tmp_path):
    module_path = REPO_ROOT / "scripts" / "render_pr_body.py"
    spec = importlib.util.spec_from_file_location("render_pr_body_wrapper", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    output = tmp_path / "pr-body.md"
    original_argv = sys.argv[:]
    try:
        sys.argv = [
            "render_pr_body.py",
            "--project-name",
            "Bluefin",
            "--primary-image",
            "bluefin",
            "--variants-json",
            '[{"image":"bluefin"}]',
            "--repo",
            "projectbluefin/bluefin",
            "--run-url",
            "https://github.com/example/runs/1",
            "--date",
            "2026-06-11",
            "--output",
            str(output),
        ]
        module.main()
    finally:
        sys.argv = original_argv

    body = output.read_text(encoding="utf-8")
    assert "Bluefin testing → stable" in body
    assert "### Variants being promoted" in body
