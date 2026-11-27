"""Run the sync-branches divergence decision against real git history (issue #543).

``test_sync_branches_force_reset.py`` checks that the guard's text is present in
the workflow. These tests execute the ``diverge`` step's shell, taken from the
workflow YAML so no copy can drift, against a scratch repository whose
``origin`` holds the source and target branches. ``gh`` is replaced by a stub
on PATH so the default-branch lookup can succeed, fail, or return a branch.
"""
import os
from pathlib import Path
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "reusable-sync-branches.yml"
)


def _step(step_id=None, name=None):
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["sync"]["steps"]
    return next(s for s in steps if (step_id and s.get("id") == step_id) or s.get("name") == name)


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(cwd, name):
    (Path(cwd) / name).write_text(name)
    _git(cwd, "add", name)
    _git(cwd, "commit", "-q", "-m", name)


@pytest.fixture
def repo(tmp_path):
    """A clone whose origin has main and testing; testing is ahead by one commit."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
        _git(work, "config", key, value)
    _commit(work, "base")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "origin", "main")
    _git(work, "checkout", "-q", "-b", "testing")
    _commit(work, "renovate-digest")
    _git(work, "push", "-q", "origin", "testing")
    _git(work, "checkout", "-q", "main")
    _commit(work, "ci-fix")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "branch", "-q", "-D", "testing")
    _git(work, "fetch", "-q", "origin")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        '#!/bin/sh\necho "$*" >> "$GH_LOG"\n'
        '[ -n "$GH_DEFAULT_BRANCH" ] || exit 1\necho "$GH_DEFAULT_BRANCH"\n'
    )
    gh.chmod(0o755)
    output = tmp_path / "output"
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        GH_LOG=str(tmp_path / "gh.log"),
        GITHUB_OUTPUT=str(output),
        GITHUB_REPOSITORY="example/repo",
        SOURCE_BRANCH="main",
        TARGET_BRANCH="testing",
        ALLOW_FORCE_RESET="false",
        DEFAULT_BRANCH="main",
        GH_DEFAULT_BRANCH="",
    )

    def run(step, **overrides):
        output.write_text("")
        result = subprocess.run(
            ["bash", "-c", step["run"]],
            cwd=work,
            env=dict(env, **overrides),
            capture_output=True,
            text=True,
        )
        outputs = dict(
            line.split("=", 1) for line in output.read_text().splitlines() if "=" in line
        )
        return result, outputs

    def gh_calls():
        log = Path(env["GH_LOG"])
        return log.read_text().splitlines() if log.exists() else []

    return work, remote, run, gh_calls


def test_behind_target_fast_forwards(repo):
    work, _, run, _ = repo
    _git(work, "push", "-q", "origin", "+main:testing")
    _commit(work, "next")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "fetch", "-q", "origin")
    result, out = run(_step("diverge"))
    assert result.returncode == 0, result.stderr
    assert out == {"ahead": "0", "strategy": "merge"}


def test_diverged_without_opt_in_refuses(repo):
    _, _, run, gh_calls = repo
    result, out = run(_step("diverge"))
    assert result.returncode == 0, result.stderr
    assert out == {"ahead": "1", "strategy": "refuse"}
    assert gh_calls() == []


def test_opted_in_non_default_target_force_resets(repo):
    _, _, run, _ = repo
    result, out = run(_step("diverge"), ALLOW_FORCE_RESET="true")
    assert result.returncode == 0, result.stderr
    assert out["strategy"] == "force-reset"


def test_opted_in_default_branch_target_refuses(repo):
    _, _, run, _ = repo
    result, out = run(_step("diverge"), ALLOW_FORCE_RESET="true", DEFAULT_BRANCH="testing")
    assert result.returncode == 0, result.stderr
    assert out["strategy"] == "refuse"
    assert "default branch" in result.stdout


def test_missing_event_default_branch_is_resolved_through_the_api(repo):
    """Scheduled callers have no github.event.repository; the API answer is used."""
    _, _, run, gh_calls = repo
    result, out = run(
        _step("diverge"), ALLOW_FORCE_RESET="true", DEFAULT_BRANCH="", GH_DEFAULT_BRANCH="testing"
    )
    assert result.returncode == 0, result.stderr
    assert out["strategy"] == "refuse"
    assert gh_calls() == ["api repos/example/repo --jq .default_branch"]


def test_api_resolved_default_branch_elsewhere_allows_opted_in_reset(repo):
    _, _, run, _ = repo
    result, out = run(
        _step("diverge"), ALLOW_FORCE_RESET="true", DEFAULT_BRANCH="", GH_DEFAULT_BRANCH="main"
    )
    assert result.returncode == 0, result.stderr
    assert out["strategy"] == "force-reset"


def test_unresolvable_default_branch_refuses_instead_of_resetting(repo):
    _, _, run, gh_calls = repo
    result, out = run(_step("diverge"), ALLOW_FORCE_RESET="true", DEFAULT_BRANCH="")
    assert result.returncode == 0, result.stderr
    assert out["strategy"] == "refuse"
    assert "could not resolve the repository default branch" in result.stdout
    assert len(gh_calls()) == 1


def test_refusal_fails_and_leaves_remote_target_untouched(repo):
    _, remote, run, _ = repo
    before = _git(remote, "rev-parse", "testing")
    result, _ = run(_step(name="Refuse to discard diverged history"), AHEAD="1")
    assert result.returncode == 1
    assert "::error::" in result.stdout
    assert _git(remote, "rev-parse", "testing") == before


def test_opted_in_reset_moves_remote_target_onto_source(repo):
    _, remote, run, _ = repo
    result, _ = run(_step(name="Force-reset target to source (diverged)"), AHEAD="1")
    assert result.returncode == 0, result.stderr
    assert _git(remote, "rev-parse", "testing") == _git(remote, "rev-parse", "main")


def test_diverge_step_env_carries_token():
    """The gh api default-branch fallback needs GH_TOKEN, or it fails silently."""
    env = _step(step_id="diverge")["env"]
    assert env.get("GH_TOKEN") == "${{ github.token }}"
