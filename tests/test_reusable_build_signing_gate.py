"""Guard: reusable-build.yml fails the job when the pushed image is not signed.

The sign-and-publish step runs with continue-on-error so SBOM/attestation
failures stay non-fatal. The image is already pushed at that point, so a
following gate step must fail the job unless the composite reported
image-signed == 'true' (#598).
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-build.yml"

SIGN_STEP = "Sign, publish SBOM, and attest"
GATE_STEP = "Fail if the pushed image is not signed"


def _steps():
    wf = yaml.safe_load(WORKFLOW.read_text())
    for job in wf["jobs"].values():
        names = [s.get("name") for s in job.get("steps", [])]
        if SIGN_STEP in names:
            return job["steps"]
    raise AssertionError(f"no job contains {SIGN_STEP!r}")


def _step(steps, name):
    return next(s for s in steps if s.get("name") == name)


def test_sign_step_has_id_for_gate():
    sign = _step(_steps(), SIGN_STEP)
    assert sign["id"] == "sign"
    assert sign["uses"].endswith("/bootc-build/sign-and-publish")


def test_gate_step_directly_follows_sign_step():
    names = [s.get("name") for s in _steps()]
    assert names.index(GATE_STEP) == names.index(SIGN_STEP) + 1


def test_gate_step_checks_image_signed_output_and_fails():
    steps = _steps()
    sign = _step(steps, SIGN_STEP)
    gate = _step(steps, GATE_STEP)
    assert "steps.sign.outputs.image-signed != 'true'" in gate["if"]
    # Gate must run whenever signing was attempted.
    assert sign["if"] in gate["if"]
    assert "continue-on-error" not in gate
    assert "exit 1" in gate["run"]
