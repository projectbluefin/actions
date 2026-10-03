"""Guard: sign-and-publish exposes a signing-only success signal.

reusable-build.yml wraps bootc-build/sign-and-publish in continue-on-error so
SBOM and attestation hiccups never block image publishing. The image is pushed
before that step runs, so without a separate signal a failed `cosign sign`
leaves the mutable tag pointing at an unsigned image while the job stays green.

The `image-signed` output is that signal. It must be produced by a step that
sits after every image-signature step (sign, verify, legacy .sig assertion) and
before the first SBOM/attestation step, and it must never carry a conditional
that could let it run when signing was skipped.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
ACTION = REPO_ROOT / "bootc-build" / "sign-and-publish" / "action.yml"

SIGNATURE_STEPS = (
    "Sign container image (keyless)",
    "Sign container image (key-based)",
    "Verify signature",
    "Assert legacy .sig tag exists (podman/bootc compatibility)",
)
FIRST_SBOM_STEP = "Install Syft"


def _load():
    return yaml.safe_load(ACTION.read_text())


def _step_names(action):
    return [step.get("name") for step in action["runs"]["steps"]]


def test_image_signed_output_wired_to_mark_signed_step():
    action = _load()
    output = action["outputs"]["image-signed"]
    assert output["value"] == "${{ steps.mark-signed.outputs.signed }}"


def test_mark_signed_runs_after_signature_steps_and_before_sbom():
    action = _load()
    names = _step_names(action)
    mark = names.index("Mark image signed")
    for name in SIGNATURE_STEPS:
        assert names.index(name) < mark, f"{name!r} must precede the signed marker"
    assert mark < names.index(FIRST_SBOM_STEP)


def test_mark_signed_step_is_unconditional_and_sets_output():
    action = _load()
    step = next(s for s in action["runs"]["steps"] if s.get("name") == "Mark image signed")
    assert step["id"] == "mark-signed"
    assert "if" not in step
    assert 'echo "signed=true" >> "$GITHUB_OUTPUT"' in step["run"]
