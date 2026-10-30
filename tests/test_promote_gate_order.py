from pathlib import Path

import yaml


WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "reusable-promote-squash.yml"
)


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _jobs():
    return _workflow()["jobs"]


def _call_inputs():
    document = _workflow()
    # YAML 1.1 resolves the bare `on` key to True, which is what PyYAML hands back.
    triggers = document.get("on", document.get(True))
    return triggers["workflow_call"]["inputs"]


def _render_step():
    return next(
        step for step in _jobs()["promote"]["steps"] if step.get("id") == "render"
    )


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
    assert "needs.gate.outputs.ready == 'true'" in jobs["enqueue"]["if"]


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


def test_explicit_gate_failure_opens_actionable_issue():
    jobs = _jobs()
    assert "report-gate-failure" in jobs
    assert "needs.gate.result == 'failure'" in jobs["report-gate-failure"]["if"]
    script = jobs["report-gate-failure"]["steps"][0]["with"]["script"]
    assert "priority/p1" in script


def test_auto_merge_defaults_to_todays_rendered_body():
    auto_merge = _call_inputs()["auto_merge"]
    assert auto_merge["type"] == "boolean"
    assert auto_merge["default"] is True


def test_pr_body_merge_note_is_policy_not_release_window_state():
    # enqueue_promotion is false on every refresh event in the bluefin model, so
    # forwarding it here would advertise "merged by a human" for the whole week
    # between release windows. The body describes the repository's merge policy.
    forwarded = _render_step()["with"]["auto_merge"]
    assert forwarded == "${{ inputs.auto_merge }}"
    assert "enqueue_promotion" not in forwarded


def test_merge_note_is_forwarded_to_render_step():
    assert _call_inputs()["merge_note"]["default"] == ""
    assert _render_step()["with"]["merge_note"] == "${{ inputs.merge_note }}"


def test_e2e_status_context_is_forwarded_to_release_gate():
    gate_inputs = _jobs()["gate"]["with"]
    assert gate_inputs["e2e_status_context"] == "${{ inputs.e2e_status_context }}"

    workflow = WORKFLOW.read_text()
    assert "      e2e_status_context:\n" in workflow
