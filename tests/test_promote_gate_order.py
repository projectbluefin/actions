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


def test_release_gate_runs_only_for_enqueuing_events():
    jobs = _jobs()
    assert "inputs.enqueue_promotion" in jobs["gate"]["if"]


def test_do_not_merge_decision_is_shared_with_enqueue_job():
    jobs = _jobs()
    assert jobs["promote"]["outputs"]["do_not_merge_blocked"] == (
        "${{ steps.check-dnm.outputs.blocked }}"
    )
    assert "needs.promote.outputs.do_not_merge_blocked != 'true'" in jobs["enqueue"]["if"]


def test_queue_and_auto_merge_enrollment_are_idempotent():
    scripts = [step.get("run", "") for step in _jobs()["enqueue"]["steps"]]
    script = next(script for script in scripts if "enqueuePullRequest" in script)
    assert "mergeQueueEntry" in script
    assert "is already queued" in script
    assert "autoMergeRequest" in script
    assert "already enabled" in script

def test_validate_status_is_posted_only_after_release_gate():
    jobs = _jobs()
    enqueue_scripts = [step.get("run", "") for step in jobs["enqueue"]["steps"]]
    promote_scripts = [step.get("run", "") for step in jobs["promote"]["steps"]]
    assert any("--field context=validate" in script for script in enqueue_scripts)
    assert not any("--field context=validate" in script for script in promote_scripts)
    assert any(
        step.get("name") == "Clear stale release labels on refresh"
        for step in jobs["promote"]["steps"]
    )


def test_e2e_status_context_is_forwarded_to_release_gate():
    gate_inputs = _jobs()["gate"]["with"]
    assert gate_inputs["e2e_status_context"] == "${{ inputs.e2e_status_context }}"

    workflow = WORKFLOW.read_text()
    assert "      e2e_status_context:\n" in workflow
