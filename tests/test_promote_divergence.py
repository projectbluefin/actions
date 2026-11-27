import os
from pathlib import Path
import subprocess

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/reusable-promote-squash.yml"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def test_divergence_stops_promotion_and_disarms_existing_pr(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "testing")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (repo / "file").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    git(repo, "branch", "main")
    (repo / "source").write_text("source\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "source change")
    source = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    (repo / "target").write_text("target\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "target-only change")
    target = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/testing", source)
    git(repo, "update-ref", "refs/remotes/origin/main", target)

    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["promote"]["steps"]
    compare = next(s for s in steps if s.get("id") == "compare")
    stop = next(s for s in steps if s.get("name") == "Stop unsafe promotion")
    rebuild = next(s for s in steps if s.get("id") == "rebuild")
    assert "sync_needed == 'true'" in rebuild["if"]
    assert "needs.promote.outputs.sync_needed == 'true'" in workflow["jobs"]["gate"]["if"]
    assert "needs.gate.result == 'success'" in workflow["jobs"]["enqueue"]["if"]

    output = tmp_path / "output"
    output.touch()
    calls = tmp_path / "calls"
    comments = tmp_path / "comments"
    comments.touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
case "$1 $2" in
  "pr list") echo 42 ;;
  "pr view") printf 'PR_node\\ttrue\\n' ;;
  "api graphql") if [[ "$*" == *'query('* ]]; then echo queue; fi ;;
  "api --paginate") cat "$COMMENTS" ;;
  "pr comment") printf '%s\\n' "${@: -1}" >> "$COMMENTS" ;;
esac
''')
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(output),
           "SOURCE_BRANCH": "testing", "TARGET_BRANCH": "main", "PROMOTION_BRANCH": "auto/promote-testing-to-main",
           "SOURCE_SHA": source, "TARGET_SHA": target, "REPO": "example/repo", "CALLS": str(calls), "COMMENTS": str(comments)}
    result = subprocess.run(["bash", "-c", compare["run"]], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert "target_ahead=true" in output.read_text()
    assert "sync_needed=false" in output.read_text()
    result = subprocess.run(["bash", "-c", stop["run"]], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert "::warning::" in result.stdout and "target-only change" in result.stdout
    assert "--disable-auto" in calls.read_text()
    assert "dequeuePullRequest" in calls.read_text()
    assert "target-only change" in comments.read_text()
    subprocess.run(["bash", "-c", stop["run"]], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert calls.read_text().count("pr comment") == 1

    git(repo, "update-ref", "refs/remotes/origin/main", git(repo, "rev-parse", f"{source}^"))
    output.write_text("")
    subprocess.run(["bash", "-c", compare["run"]], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert "target_ahead=false" in output.read_text()
    assert "sync_needed=true" in output.read_text()
