"""Injection gate for the reusable sync-branches workflow.

The ``reusable-sync-branches.yml`` workflow merges one branch into another and,
when they diverge, may force-reset the target. Its ``source_branch`` and
``target_branch`` come from the caller workflow as ``inputs``. GitHub expands
``${{ inputs.* }}`` inline inside a ``run:`` block *before* the shell sees it,
which is a command-injection surface: a caller-controlled value lands directly
in a shell line.

The fix moves every branch value into an ``env:`` block and references it as a
quoted shell variable (``${SOURCE_BRANCH}`` / ``${TARGET_BRANCH}``). These tests
pin that behaviour: no ``run:`` block may interpolate ``${{ inputs.* }}`` again,
the merge and force-reset steps must still receive their branches through
``env:``, and the force-reset must keep pinning the target with
``--force-with-lease`` so a concurrent push cannot clobber the lease.
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

# Every step that touches a branch name must declare that name in its own
# ``env:`` block and reference it as a shell variable, never as an inline
# ``${{ inputs.* }}``.
_BRANCH_ENV_VARS = {"SOURCE_BRANCH", "TARGET_BRANCH"}


def _steps():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["sync"]["steps"]


def _step_by_id(step_id):
    return next(step for step in _steps() if step.get("id") == step_id)


def _step_by_name(name):
    return next(step for step in _steps() if step["name"] == name)


def test_no_run_block_interpolates_inputs():
    """No shell step may expand ``${{ inputs.* }}`` inline."""
    for step in _steps():
        run = step.get("run", "")
        assert "${{ inputs." not in run, (
            f"step {step['name']!r} interpolates an input inline; pass it via env:"
        )


def test_check_step_declares_branch_inputs_in_env():
    """The 'Check if sync is needed' step gets its branches through env."""
    step = _step_by_id("check")
    env = step.get("env", {})
    assert env["SOURCE_BRANCH"] == "${{ inputs.source_branch }}"
    assert env["TARGET_BRANCH"] == "${{ inputs.target_branch }}"
    run = step["run"]
    assert "${SOURCE_BRANCH}" in run and "${TARGET_BRANCH}" in run


def test_detect_divergence_step_declares_branch_inputs_in_env():
    """The 'Detect divergence' step gets its branches through env."""
    step = _step_by_id("diverge")
    env = step.get("env", {})
    assert env["SOURCE_BRANCH"] == "${{ inputs.source_branch }}"
    assert env["TARGET_BRANCH"] == "${{ inputs.target_branch }}"
    run = step["run"]
    assert "${SOURCE_BRANCH}" in run and "${TARGET_BRANCH}" in run


def test_merge_step_declares_branch_inputs_in_env():
    """The fast-forward merge step gets its branches through env."""
    step = _step_by_name("Merge source into target (fast-forward)")
    env = step.get("env", {})
    assert env["SOURCE_BRANCH"] == "${{ inputs.source_branch }}"
    assert env["TARGET_BRANCH"] == "${{ inputs.target_branch }}"
    run = step["run"]
    checkout = _first_line(run, "git checkout")
    assert checkout is not None
    assert checkout.strip() == 'git checkout "${TARGET_BRANCH}"'
    assert "origin/${SOURCE_BRANCH}" in run
    assert "${{ inputs." not in run


def test_force_reset_step_declares_branch_inputs_in_env():
    """The force-reset step gets its branches and headroom through env."""
    step = _step_by_name("Force-reset target to source (diverged)")
    env = step.get("env", {})
    assert env["SOURCE_BRANCH"] == "${{ inputs.source_branch }}"
    assert env["TARGET_BRANCH"] == "${{ inputs.target_branch }}"
    assert env["AHEAD"] == "${{ steps.diverge.outputs.ahead }}"
    run = step["run"]
    assert "${SOURCE_BRANCH}" in run and "${TARGET_BRANCH}" in run
    assert "${{ inputs." not in run


def test_force_reset_still_pins_target_with_lease():
    """The force-reset must keep pinning the target so a concurrent push is blocked."""
    run = _step_by_name("Force-reset target to source (diverged)")["run"]
    assert '--force-with-lease="${TARGET_BRANCH}:${TARGET_SHA}"' in run


def test_branch_referenced_as_env_not_input_in_every_step():
    """Wherever a step names a branch, it must come from an env var, not an input."""
    for step in _steps():
        run = step.get("run", "")
        env = step.get("env", {}) or {}
        declared = _BRANCH_ENV_VARS & set(env)
        for var in declared:
            assert f"${{{var}}}" in run, (
                f"step {step['name']!r} declares {var} in env but never uses it"
            )


def _first_line(text, prefix):
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line
    return None
