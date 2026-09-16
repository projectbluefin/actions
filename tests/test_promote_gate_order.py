from pathlib import Path

import yaml


WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "reusable-promote-squash.yml"
)


def _jobs():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def test_queue_enrollment_runs_only_after_release_gate_succeeds():
    jobs = _jobs()

    assert "enqueue" in jobs
    assert set(jobs["enqueue"]["needs"]) == {"promote", "gate"}
    assert "inputs.enqueue_promotion" in jobs["enqueue"]["if"]
    assert "needs.gate.result == 'success'" in jobs["enqueue"]["if"]

    enqueue_steps = jobs["enqueue"]["steps"]
    assert any("enqueuePullRequest" in step.get("run", "") for step in enqueue_steps)
    assert not any(
        "enqueuePullRequest" in step.get("run", "")
        for step in jobs["promote"]["steps"]
    )
