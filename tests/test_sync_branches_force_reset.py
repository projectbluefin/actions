"""Behavioural guard for the force-reset safety fix (issue #543).

``reusable-sync-branches.yml`` used to force-reset the target branch onto the
source branch whenever the two diverged, discarding whatever was ahead on the
target. That wiped real history (an attempted 100-commit wipe of a project's
main branch). The fix makes a force-reset opt-in and forbids it on the
repository's default branch.

These tests pin the *shape* of that guard in the workflow YAML: the
``allow_force_reset`` input defaults to false, the divergence step refuses when
it is not opted in, refuses when the target is the default branch, and a
separate step fails the job loudly on refusal instead of pushing.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "reusable-sync-branches.yml"
)


def _trigger():
    # PyYAML parses the bare ``on:`` key as the boolean True (YAML 1.1).
    return _workflow()[True]["workflow_call"]


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps():
    return _workflow()["jobs"]["sync"]["steps"]


def _step_by_id(step_id):
    return next(s for s in _steps() if s.get("id") == step_id)


def _step_by_name(name):
    return next(s for s in _steps() if s["name"] == name)


def test_allow_force_reset_input_defaults_false():
    """The opt-in defaults to off, so divergence fails closed by default."""
    inputs = _trigger()["inputs"]
    force = inputs["allow_force_reset"]
    assert force["type"] == "boolean"
    assert force["default"] is False


def test_divergence_step_declares_guard_env():
    """The divergence step receives the opt-in flag and default branch via env."""
    env = _step_by_id("diverge")["env"]
    assert env["ALLOW_FORCE_RESET"] == "${{ inputs.allow_force_reset }}"
    assert "DEFAULT_BRANCH" in env


def test_refuses_when_not_opted_in():
    """Without allow_force_reset:true the diverged target is refused, not reset."""
    run = _step_by_id("diverge")["run"]
    assert 'ALLOW_FORCE_RESET" != "true"' in run
    assert "strategy=refuse" in run


def test_refuses_on_default_branch():
    """A force-reset is never permitted on the repository default branch."""
    run = _step_by_id("diverge")["run"]
    assert '"$TARGET_BRANCH" = "$DEFAULT_BRANCH"' in run
    assert "default branch" in run


def test_refusal_fails_the_job():
    """Refusal must fail the job (exit 1) so a human notices instead of silent data loss."""
    refuse = _step_by_name("Refuse to discard diverged history")
    assert refuse["if"].strip().endswith("strategy == 'refuse'")
    assert (run := refuse.get("run", ""))
    assert "exit 1" in run


def test_force_reset_step_still_present_and_leased():
    """The opt-in path still force-resets, pinned with --force-with-lease."""
    reset = _step_by_name("Force-reset target to source (diverged)")
    assert reset["if"].strip().endswith("strategy == 'force-reset'")
    assert "--force-with-lease" in reset["run"]
