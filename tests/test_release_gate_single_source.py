"""Drift gate for the release-gate digest/signature logic.

`.github/workflows/reusable-release-gate.yml` carries the *shipped* implementation
of digest resolution and cosign verification as inline `run:` bodies, while
`scripts/resolve_digests.sh` and `scripts/verify_signatures.sh` carry the copies
that `tests/bats/test_release_gate.bats` actually exercises. Nothing invokes the
scripts at runtime, so without this gate the BATS suite can stay green while the
shipped gate regresses. These tests make the two copies provably identical.

The workflow and the scripts differ in exactly one respect: the workflow reads
`${{ steps.resolve.outputs.ok }}` where the script reads `${RESOLVE_OK}`. That
substitution is declared once, in NORMALISATIONS, and applied before comparison
so every *other* difference fails the build.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-release-gate.yml"

# step id in reusable-release-gate.yml -> script holding the extracted copy
STEP_TO_SCRIPT = {
    "resolve": REPO_ROOT / "scripts" / "resolve_digests.sh",
    "verify": REPO_ROOT / "scripts" / "verify_signatures.sh",
}

# The only sanctioned divergences between an inline step body and its script.
# Each entry maps a workflow-expression form to the env-var form the script uses.
# Keep this table minimal: every entry is a place where the drift gate is blind.
NORMALISATIONS = {
    "verify": [("'${{ steps.resolve.outputs.ok }}'", '"${RESOLVE_OK}"')],
}


def _gate_steps():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return {
        step["id"]: step
        for step in workflow["jobs"]["gate"]["steps"]
        if isinstance(step, dict) and "id" in step
    }


def _script_body(path: Path) -> str:
    """Return the script minus its shebang and leading header comment block."""
    lines = path.read_text().splitlines()
    start = 0
    if lines and lines[start].startswith("#!"):
        start += 1
    while start < len(lines) and (
        lines[start].startswith("#") or lines[start].strip() == ""
    ):
        start += 1
    return "\n".join(lines[start:]).strip()


@pytest.mark.parametrize("step_id", sorted(STEP_TO_SCRIPT))
def test_script_exists_for_gate_step(step_id):
    assert STEP_TO_SCRIPT[step_id].is_file()
    assert step_id in _gate_steps()


def _normalised_inline(step_id, run_body):
    for expression, env_form in NORMALISATIONS.get(step_id, []):
        run_body = run_body.replace(expression, env_form)
    return run_body.strip()


@pytest.mark.parametrize("step_id", sorted(STEP_TO_SCRIPT))
def test_inline_step_matches_extracted_script(step_id):
    """The workflow step body and its extracted script must not drift apart."""
    inline = _normalised_inline(step_id, _gate_steps()[step_id]["run"])
    extracted = _script_body(STEP_TO_SCRIPT[step_id])
    assert inline == extracted, (
        f"jobs.gate step '{step_id}' in {WORKFLOW.relative_to(REPO_ROOT)} has drifted "
        f"from {STEP_TO_SCRIPT[step_id].relative_to(REPO_ROOT)}. Update both copies "
        f"together, or collapse them into one."
    )


@pytest.mark.parametrize("step_id", sorted(STEP_TO_SCRIPT))
def test_gate_step_declares_its_inputs_via_env(step_id):
    """Each compared step must pass its inputs through `env:`, not bare globals."""
    assert _gate_steps()[step_id].get(
        "env"
    ), f"jobs.gate step '{step_id}' declares no env: block"


@pytest.mark.parametrize("step_id", sorted(STEP_TO_SCRIPT))
def test_no_unsanctioned_expression_interpolation(step_id):
    """Expressions interpolated into shell must be declared in NORMALISATIONS.

    Anything else is both a script-injection surface and a hole in the drift gate,
    so it has to be routed through the step's `env:` block instead.
    """
    leftover = _normalised_inline(step_id, _gate_steps()[step_id]["run"])
    assert "${{" not in leftover, (
        f"jobs.gate step '{step_id}' interpolates an undeclared GitHub expression "
        f"into its shell body; pass it through the step's env: block instead."
    )


def test_normalisation_table_has_no_dead_entries():
    """A normalisation that no longer applies is stale and must be removed."""
    steps = _gate_steps()
    for step_id, pairs in NORMALISATIONS.items():
        assert step_id in STEP_TO_SCRIPT, f"unknown step id '{step_id}'"
        for expression, _ in pairs:
            assert expression in steps[step_id]["run"], (
                f"normalisation {expression!r} no longer matches jobs.gate step "
                f"'{step_id}'; delete it so the drift gate stays tight."
            )
