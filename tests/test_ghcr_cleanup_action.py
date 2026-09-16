"""Tests and drift guards for bootc-build/ghcr-cleanup action.

Guards against destructive regressions in GHCR container image pruning:
1. Pinned SHA: third-party action dataaxiom/ghcr-cleanup-action must stay pinned
   to a full 40-character commit SHA to prevent supply-chain compromises.
2. Safe retention defaults: keep-n-tagged and keep-n-untagged must be >= 1, and
   older-than must be non-empty, preventing accidental deletion of live images.
3. Input forwarding: every input declared on the composite action must be
   forwarded to the wrapped cleanup step.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTION_PATH = REPO_ROOT / "bootc-build" / "ghcr-cleanup" / "action.yml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ghcr-cleanup.yml"

PINNED_ACTION_PATTERN = re.compile(r"^dataaxiom/ghcr-cleanup-action@[0-9a-f]{40}$")


def load_action_manifest(path: Path = ACTION_PATH) -> dict[str, Any]:
    """Load and parse the composite action YAML manifest."""
    assert path.is_file(), f"Action file not found: {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def get_cleanup_step(manifest: dict[str, Any]) -> dict[str, Any]:
    """Extract the dataaxiom/ghcr-cleanup-action step from the composite action."""
    assert manifest.get("runs", {}).get("using") == "composite", "Action must be composite"
    steps = manifest.get("runs", {}).get("steps", [])
    assert steps, "Action must contain at least one step"
    for step in steps:
        uses = step.get("uses", "")
        if "dataaxiom/ghcr-cleanup-action" in uses:
            return step
    pytest.fail("No step found using dataaxiom/ghcr-cleanup-action")


def validate_uses_ref(uses_ref: str) -> None:
    """Assert that the third-party action is pinned to a full 40-character hex SHA."""
    if not PINNED_ACTION_PATTERN.match(uses_ref):
        raise ValueError(
            f"Third-party action '{uses_ref}' must match pattern "
            f"'{PINNED_ACTION_PATTERN.pattern}' (pinned to a full 40-char SHA)."
        )


def validate_retention_defaults(inputs: dict[str, Any]) -> None:
    """Assert that retention count defaults are >= 1 and older-than is non-empty."""
    for count_key in ("keep-n-tagged", "keep-n-untagged"):
        assert count_key in inputs, f"Declared inputs must include '{count_key}'"
        default_val = inputs[count_key].get("default")
        assert default_val is not None, f"Input '{count_key}' must declare a default"
        try:
            int_val = int(default_val)
        except (ValueError, TypeError) as err:
            raise ValueError(
                f"Input '{count_key}' default must parse as an integer: {default_val!r}"
            ) from err
        if int_val < 1:
            raise ValueError(
                f"Input '{count_key}' default must be >= 1 to prevent destructive pruning; got {int_val}"
            )

    assert "older-than" in inputs, "Declared inputs must include 'older-than'"
    older_than = inputs["older-than"].get("default")
    assert older_than is not None, "Input 'older-than' must declare a default"
    if not str(older_than).strip():
        raise ValueError("Input 'older-than' default must not be empty")


def validate_input_forwarding(inputs: dict[str, Any], step_with: dict[str, Any]) -> None:
    """Assert that every input declared in the action is forwarded to the wrapped step."""
    forwarded_values = [str(v) for v in step_with.values()]
    for input_name in inputs:
        expected_ref = f"inputs.{input_name}"
        forwarded = any(expected_ref in val for val in forwarded_values)
        if not forwarded:
            raise ValueError(
                f"Declared input '{input_name}' is not forwarded to wrapped step with: block. "
                f"Expected expression referencing '{expected_ref}'."
            )


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return load_action_manifest()


@pytest.fixture(scope="module")
def cleanup_step(manifest: dict[str, Any]) -> dict[str, Any]:
    return get_cleanup_step(manifest)


class TestGhcrCleanupActionManifest:
    """Tests for bootc-build/ghcr-cleanup/action.yml."""

    def test_composite_action_structure(self, manifest: dict[str, Any]):
        assert manifest.get("name") == "bootc-build/ghcr-cleanup"
        assert manifest.get("runs", {}).get("using") == "composite"
        assert len(manifest.get("runs", {}).get("steps", [])) >= 1

    def test_third_party_action_is_pinned_to_full_sha(self, cleanup_step: dict[str, Any]):
        uses = cleanup_step.get("uses", "")
        validate_uses_ref(uses)

    def test_required_inputs_are_declared(self, manifest: dict[str, Any]):
        inputs = manifest.get("inputs", {})
        assert inputs.get("packages", {}).get("required") is True
        assert inputs.get("github-token", {}).get("required") is True

    def test_retention_defaults_are_safe(self, manifest: dict[str, Any]):
        inputs = manifest.get("inputs", {})
        validate_retention_defaults(inputs)

    def test_every_declared_input_is_forwarded(
        self, manifest: dict[str, Any], cleanup_step: dict[str, Any]
    ):
        inputs = manifest.get("inputs", {})
        step_with = cleanup_step.get("with", {})
        validate_input_forwarding(inputs, step_with)


class TestValidationGuards:
    """Negative unit tests to ensure validation logic catches dangerous regressions."""

    def test_rejects_mutable_tag(self):
        with pytest.raises(ValueError, match="pinned to a full 40-char SHA"):
            validate_uses_ref("dataaxiom/ghcr-cleanup-action@v1")

    def test_rejects_short_sha(self):
        with pytest.raises(ValueError, match="pinned to a full 40-char SHA"):
            validate_uses_ref("dataaxiom/ghcr-cleanup-action@d52806a")

    def test_rejects_zero_keep_n_tagged(self):
        inputs = {
            "keep-n-tagged": {"default": "0"},
            "keep-n-untagged": {"default": "7"},
            "older-than": {"default": "90 days"},
        }
        with pytest.raises(ValueError, match="must be >= 1"):
            validate_retention_defaults(inputs)

    def test_rejects_negative_keep_n_untagged(self):
        inputs = {
            "keep-n-tagged": {"default": "7"},
            "keep-n-untagged": {"default": "-1"},
            "older-than": {"default": "90 days"},
        }
        with pytest.raises(ValueError, match="must be >= 1"):
            validate_retention_defaults(inputs)

    def test_rejects_non_integer_retention_default(self):
        inputs = {
            "keep-n-tagged": {"default": "seven"},
            "keep-n-untagged": {"default": "7"},
            "older-than": {"default": "90 days"},
        }
        with pytest.raises(ValueError, match="must parse as an integer"):
            validate_retention_defaults(inputs)

    def test_rejects_empty_older_than(self):
        inputs = {
            "keep-n-tagged": {"default": "7"},
            "keep-n-untagged": {"default": "7"},
            "older-than": {"default": "   "},
        }
        with pytest.raises(ValueError, match="must not be empty"):
            validate_retention_defaults(inputs)

    def test_rejects_unforwarded_input(self):
        inputs = {
            "packages": {},
            "unforwarded-param": {},
        }
        step_with = {
            "packages": "${{ inputs.packages }}",
        }
        with pytest.raises(ValueError, match="Declared input 'unforwarded-param' is not forwarded"):
            validate_input_forwarding(inputs, step_with)


class TestGhcrCleanupWorkflow:
    """Guards for .github/workflows/ghcr-cleanup.yml schedule and invocation safety."""

    def test_workflow_callers_provide_required_inputs(self):
        workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
        cleanup_job = workflow.get("jobs", {}).get("cleanup", {})
        steps = cleanup_job.get("steps", [])
        action_steps = [s for s in steps if s.get("uses", "").endswith("bootc-build/ghcr-cleanup")]
        assert len(action_steps) >= 1, "Workflow must contain at least one cleanup step"

        for step in action_steps:
            step_with = step.get("with", {})
            assert "packages" in step_with and step_with["packages"].strip()
            assert "github-token" in step_with and step_with["github-token"].strip()

            if "keep-n-tagged" in step_with:
                assert int(step_with["keep-n-tagged"]) >= 1
            if "keep-n-untagged" in step_with:
                assert int(step_with["keep-n-untagged"]) >= 1
            if "older-than" in step_with:
                assert str(step_with["older-than"]).strip()
