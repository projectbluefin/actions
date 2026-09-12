"""Contract tests for the caller-scoped reusable Renovate workflow."""
from pathlib import Path

import pytest


yaml = pytest.importorskip("yaml")

WORKFLOW = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "reusable-renovate.yml"
)


def _run_renovate_step():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(
        step
        for step in workflow["jobs"]["renovate"]["steps"]
        if step["name"] == "Run Renovate"
    )


def test_reusable_renovate_targets_only_its_caller_repository():
    """Every invocation must explicitly scope Renovate to its caller."""
    env = _run_renovate_step()["env"]

    assert env["RENOVATE_REPOSITORIES"] == "${{ github.repository }}"
    assert "RENOVATE_AUTODISCOVER" not in env


def test_reusable_renovate_preserves_dry_run_logging_contract():
    """Caller repository scoping must not alter existing dry-run behavior."""
    env = _run_renovate_step()["env"]

    assert env["LOG_LEVEL"] == "${{ inputs.dry_run == true && 'debug' || 'info' }}"
    assert env["RENOVATE_DRY_RUN"] == "${{ inputs.dry_run == true && 'full' || '' }}"
