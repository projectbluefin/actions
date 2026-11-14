"""Tests for the consumer-facing thin-caller reusable workflow."""
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).parent.parent
REUSABLE = REPO_ROOT / ".github" / "workflows" / "reusable-thin-caller-gate.yml"


def test_reusable_declares_workflow_call():
    workflow = yaml.safe_load(REUSABLE.read_text(encoding="utf-8"))
    # YAML 1.1 parses the bare key `on:` as boolean True under PyYAML.
    on_key = "on" if "on" in workflow else True
    assert "workflow_call" in workflow[on_key]


def test_reusable_runs_canonical_script():
    body = REUSABLE.read_text(encoding="utf-8")
    assert "projectbluefin/actions" in body
    assert "validate_thin_caller.py" in body
    assert "--max-lines 50" in body


def test_reusable_script_source_is_a_configurable_input():
    # The script checkout must source from workflow_call inputs, not a value
    # hardcoded into the checkout step. A consumer pinning a future @v2 gets
    # that version's own default; validating a fork/branch of this reusable
    # (as issue #546 did) overrides the inputs instead of editing the step
    # (issue #546 review finding: a bare `ref: v1` cannot be overridden and
    # silently drifts independently of the ref the consumer actually invoked).
    workflow = yaml.safe_load(REUSABLE.read_text(encoding="utf-8"))
    on_key = "on" if "on" in workflow else True
    inputs = workflow[on_key]["workflow_call"]["inputs"]
    assert inputs["actions_repository"]["default"] == "projectbluefin/actions"
    assert inputs["actions_ref"]["default"] == ""

    job = workflow["jobs"]["thin-caller-gate"]
    checkout_steps = [s for s in job["steps"] if s.get("with", {}).get("path") == "thin-caller-gate"]
    assert len(checkout_steps) == 1
    assert checkout_steps[0]["with"]["repository"] == "${{ inputs.actions_repository }}"
    assert checkout_steps[0]["with"]["ref"] == "${{ inputs.actions_ref || job.workflow_sha }}"


def test_reusable_documents_job_level_opt_in():
    # Reusable workflows can only be called at the job level (`jobs.<id>.uses`),
    # never as a step. The documented opt-in snippet must model that, or a
    # consumer copying it verbatim gets a workflow-file parse error ("can't
    # be used with steps") and the gate never runs.
    body = REUSABLE.read_text(encoding="utf-8")
    self_ref = "projectbluefin/actions/.github/workflows/reusable-thin-caller-gate.yml@v1"
    assert f"jobs:\n#     thin-caller-gate:\n#       uses: {self_ref}" in body
    assert f"- uses: {self_ref}" not in body
