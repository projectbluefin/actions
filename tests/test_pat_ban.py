"""Exercise the shipped workflow shell against real commit diffs."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/pat-ban.yml").read_text())
CHECK = WORKFLOW["jobs"]["check-no-new-pats"]["steps"][1]["run"]


@pytest.mark.parametrize("reference,allowed", [
    ("secrets.MY_PAT", False),
    ("secrets.my_pat", False),
    ("secrets.My_Pat", False),
    ("secrets['MY_PAT']", False),
    ('secrets["my_pat"]', False),
    ("secrets[ 'My_Pat' ]", False),
    ("secrets.github_token", True),
    ("SECRETS['Github_Token']", True),
    ('secrets[ "GITHUB_TOKEN" ]', True),
    ("secrets.GITHUB_TOKEN_EXTRA", False),
    ("secrets.token", True),
    ("secrets.app_id", True),
    ("secrets.private_key", True),
    ("secrets.renovate_token", True),
    ("secrets[env.NAME]", False),
    ("secrets[format('{0}_PAT', 'MY')]", False),
    ("secrets['MY_PAT' || 'GITHUB_TOKEN']", False),
    ("secrets.github_token || secrets['my_pat']", False),
    ("secrets['github_token'] || secrets[env.NAME]", False),
])
def test_secret_references(tmp_path, reference, allowed):
    result = run_check(tmp_path, "token: ${{ " + reference + " }}\n")
    assert (result.returncode == 0) == allowed, result.stdout


@pytest.mark.parametrize("content,filename", [
    ("# token: ${{ secrets.my_pat }}\n", "check.yml"),
    ("name: harmless\n", "check.yaml"),
    ("token: ${{ secrets.my_pat }}\n", "notes.txt"),
    ("", "check.yml"),
])
def test_ignored_content(tmp_path, content, filename):
    assert run_check(tmp_path, content, filename).returncode == 0


def test_guard_passes_its_own_workflow(tmp_path):
    # The guard scans added YAML lines, so its own messages and patterns must not
    # read as secret references when pat-ban.yml itself is edited.
    text = (ROOT / ".github/workflows/pat-ban.yml").read_text()
    result = run_check(tmp_path, text, "pat-ban.yml")
    assert result.returncode == 0, result.stdout + result.stderr

def run_check(directory, content, filename="check.yml"):
    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "core.hooksPath=/dev/null", *args],
            cwd=directory, text=True,
        ).strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("commit", "--allow-empty", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (directory / filename).write_text(content)
    git("add", ".")
    git("commit", "-qm", "fixture")
    return subprocess.run(
        ["bash", "-c", CHECK], cwd=directory,
        env={**os.environ, "BASE_SHA": base},
        text=True, capture_output=True,
    )
