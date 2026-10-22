"""Execute render-pr-body's composite step to pin the merge notice it appends.

The merge notice is rendered by the action's shell step, not render_pr_body.py,
so these tests run that step with the inputs a caller would pass.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ACTION_DIR = (
    Path(__file__).resolve().parents[1] / ".github" / "actions" / "render-pr-body"
)
WEEKLY_NOTICE = "Auto-merge scheduled for Tuesday 04:00 UTC (bluefin/dakota)"
HUMAN_NOTICE = "This promotion is merged by a human."


def _action():
    return yaml.safe_load((ACTION_DIR / "action.yml").read_text())


def _render(tmp_path: Path, **inputs: str) -> str:
    action = _action()
    values = {name: spec.get("default", "") for name, spec in action["inputs"].items()}
    values.update(
        variants=json.dumps([{"image": "utah"}]),
        repo="projectbluefin/utah",
        run_url="https://github.com/projectbluefin/utah/actions/runs/1",
        output=str(tmp_path / "body.md"),
    )
    values.update(inputs)

    step = action["runs"]["steps"][0]
    env = dict(os.environ)
    for key, expr in step["env"].items():
        name = expr.strip().removeprefix("${{ inputs.").removesuffix(" }}")
        env[key] = str(values[name])
    env["GITHUB_ACTION_PATH"] = str(ACTION_DIR)
    env["GITHUB_OUTPUT"] = str(tmp_path / "github_output")
    env["GITHUB_WORKFLOW_REF"] = (
        "projectbluefin/utah/.github/workflows/promote.yml@refs/heads/main"
    )

    subprocess.run(["bash", "-c", step["run"]], env=env, check=True)
    return (tmp_path / "body.md").read_text()


def _screenshot_section(body: str) -> str:
    return body.split("## Desktop Screenshot\n\n", 1)[1]


def test_merge_note_input_defaults_to_empty():
    assert _action()["inputs"]["merge_note"]["default"] == ""
    assert _action()["inputs"]["merge_note"]["required"] is False


def test_default_keeps_weekly_auto_merge_notice(tmp_path):
    section = _screenshot_section(_render(tmp_path))
    assert WEEKLY_NOTICE in section
    assert HUMAN_NOTICE not in section


def test_auto_merge_false_keeps_human_notice(tmp_path):
    section = _screenshot_section(_render(tmp_path, auto_merge="false"))
    assert HUMAN_NOTICE in section
    assert WEEKLY_NOTICE not in section


def test_merge_note_replaces_built_in_notice(tmp_path):
    note = (
        "> [!CAUTION]\n"
        "> **Auto-merge runs daily at 04:00 UTC.**\n"
        "> Add `do-not-merge` to block it.\n"
    )
    section = _screenshot_section(_render(tmp_path, merge_note=note))
    assert section.startswith(note + "\n![utah desktop](")
    assert WEEKLY_NOTICE not in section
    assert HUMAN_NOTICE not in section


def test_merge_note_overrides_human_notice_too(tmp_path):
    section = _screenshot_section(
        _render(tmp_path, auto_merge="false", merge_note="Merged by release captain.")
    )
    assert section.startswith("Merged by release captain.\n\n![utah desktop](")
    assert HUMAN_NOTICE not in section


def test_merge_note_is_written_verbatim(tmp_path):
    note = r"Paths like C:\new\table and \c stay literal."
    section = _screenshot_section(_render(tmp_path, merge_note=note))
    assert section.startswith(note + "\n\n![utah desktop](")


def test_whitespace_only_merge_note_falls_back_to_built_in(tmp_path):
    section = _screenshot_section(_render(tmp_path, merge_note="  \n"))
    assert WEEKLY_NOTICE in section
