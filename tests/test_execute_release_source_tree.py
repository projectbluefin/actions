"""Behavior coverage for release source-tree binding."""

import os
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-execute-release.yml"


def _resolve_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["resolve"]["steps"]
    return next(step["run"] for step in steps if step.get("id") == "resolve-sha")


def _run_resolve(tmp_path: Path, *, source_tree: str, candidate_tree: str):
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    gh = mock_bin / "gh"
    gh.write_text(
        """#!/usr/bin/env bash
case "$2" in
  */git/ref/heads/testing) printf '%s\\n' "$SOURCE_SHA" ;;
  */git/commits/$SOURCE_SHA) printf '%s\\n' "$SOURCE_TREE" ;;
  */git/commits/$CANDIDATE_SHA) printf '%s\\n' "$CANDIDATE_TREE" ;;
  *) printf 'unexpected gh request: %s\\n' "$*" >&2; exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    output = tmp_path / "github-output"
    output.touch()
    env = dict(os.environ)
    env.update(
        PATH=f"{mock_bin}:{env['PATH']}",
        GITHUB_OUTPUT=str(output),
        GITHUB_SHA="main-sha",
        INPUT_SHA="main-sha",
        REPO="projectbluefin/bluefin",
        SOURCE_BRANCH="testing",
        SOURCE_SHA="testing-sha",
        SOURCE_TREE=source_tree,
        CANDIDATE_SHA="main-sha",
        CANDIDATE_TREE=candidate_tree,
    )
    result = subprocess.run(
        ["bash", "-c", _resolve_script()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, output.read_text(encoding="utf-8")


def test_matching_testing_tree_allows_digest_resolution(tmp_path):
    result, output = _run_resolve(
        tmp_path, source_tree="same-tree", candidate_tree="same-tree"
    )
    assert result.returncode == 0, result.stderr
    assert output == "sha=main-sha\n"


def test_advanced_testing_tree_blocks_mutable_tag_resolution(tmp_path):
    result, output = _run_resolve(
        tmp_path, source_tree="new-tree", candidate_tree="released-tree"
    )
    assert result.returncode != 0
    assert "testing advanced beyond release commit" in result.stdout
    assert output == ""
