"""Regression coverage for OCI registry canonicalization in release reusables."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).parent.parent
WORKFLOWS = {
    "promote": REPO_ROOT / ".github/workflows/reusable-promote-squash.yml",
    "gate": REPO_ROOT / ".github/workflows/reusable-release-gate.yml",
    "execute": REPO_ROOT / ".github/workflows/reusable-execute-release.yml",
}


def _workflow(name):
    return yaml.safe_load(WORKFLOWS[name].read_text())


def _step(workflow, job, identifier):
    return next(
        step
        for step in _workflow(workflow)["jobs"][job]["steps"]
        if step.get("id") == identifier or step.get("name") == identifier
    )


def _normalized_registry(workflow, input_registry, tmp_path):
    output = tmp_path / f"{workflow}-output"
    completed = subprocess.run(
        ["bash", "-c", _step(workflow, "normalize-registry", "normalize")["run"]],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GITHUB_OUTPUT": str(output),
            "INPUT_REGISTRY": input_registry,
        },
    )
    assert completed.stderr == ""
    return output.read_text().strip().removeprefix("registry=")


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize(
    ("input_registry", "expected"),
    [
        ("ghcr.io/ExampleOwner", "ghcr.io/exampleowner"),
        ("ghcr.io/projectbluefin", "ghcr.io/projectbluefin"),
        ("docker://ghcr.io/ExampleOwner", "ghcr.io/exampleowner"),
    ],
)
def test_normalize_registry_canonicalizes_public_input(
    workflow, input_registry, expected, tmp_path
):
    """Each reusable owns a lowercase, plain OCI registry prefix."""
    assert _normalized_registry(workflow, input_registry, tmp_path) == expected


def _write_skopeo_mock(tmp_path):
    calls = tmp_path / "skopeo-calls"
    mock_dir = tmp_path / "bin"
    mock_dir.mkdir()
    skopeo = mock_dir / "skopeo"
    skopeo.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$SKOPEO_CALLS"\n'
        'if [ "$1" = "inspect" ]; then\n'
        '  echo "sha256:0123456789abcdef"\n'
        "fi\n"
    )
    skopeo.chmod(0o755)
    return mock_dir, calls


def test_release_gate_resolves_candidate_from_normalized_registry(tmp_path):
    """Candidate digest lookup never constructs a mixed-case OCI reference."""
    registry = _normalized_registry("gate", "ghcr.io/ExampleOwner", tmp_path)
    mock_dir, calls = _write_skopeo_mock(tmp_path)
    output = tmp_path / "gate-output"

    subprocess.run(
        ["bash", "-c", _step("gate", "gate", "resolve")["run"]],
        check=True,
        env={
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ['PATH']}",
            "SKOPEO_CALLS": str(calls),
            "GITHUB_OUTPUT": str(output),
            "REGISTRY": registry,
            "TARGET_TAG": "testing",
            "VARIANTS_JSON": '["sample-image"]',
        },
    )

    assert calls.read_text() == (
        "inspect --format {{.Digest}} docker://ghcr.io/exampleowner/sample-image:testing\n"
    )


def test_execute_release_promotes_exact_digest_from_normalized_registry(tmp_path):
    """The source and target OCI references use the normalized registry output."""
    registry = _normalized_registry("execute", "ghcr.io/ExampleOwner", tmp_path)
    mock_dir, calls = _write_skopeo_mock(tmp_path)

    subprocess.run(
        ["bash", "-c", _step("execute", "execute", "Promote digests to target tags")["run"]],
        check=True,
        env={
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ['PATH']}",
            "SKOPEO_CALLS": str(calls),
            "REGISTRY": registry,
            "DIGESTS_JSON": '{"sample-image":"sha256:0123456789abcdef"}',
            "VARIANTS_JSON": (
                '[{"image":"sample-image","source_tag":"testing","target_tag":"stable"}]'
            ),
        },
    )

    assert calls.read_text() == (
        "copy --preserve-digests --all "
        "docker://ghcr.io/exampleowner/sample-image@sha256:0123456789abcdef "
        "docker://ghcr.io/exampleowner/sample-image:stable\n"
    )


def test_execute_release_testsuite_receives_normalized_exact_digest_reference():
    release_gate = _workflow("execute")["jobs"]["release-gate"]
    assert "needs.normalize-registry.outputs.registry" in release_gate["with"]["image"]


def test_oci_consumers_use_the_normalized_registry_output():
    """Raw caller input is confined to the preparation step in every reusable."""
    normalized = "${{ needs.normalize-registry.outputs.registry }}"

    promote_gate = _workflow("promote")["jobs"]["gate"]
    assert promote_gate["with"]["registry"] == normalized

    gate_steps = _workflow("gate")["jobs"]["gate"]["steps"]
    assert gate_steps[0]["env"]["REGISTRY_HOST"] == normalized
    assert _step("gate", "gate", "resolve")["env"]["REGISTRY"] == normalized
    assert _step("gate", "gate", "verify")["env"]["REGISTRY"] == normalized

    execute = _workflow("execute")["jobs"]
    assert _step("execute", "resolve", "Authenticate to GHCR")["env"]["REGISTRY"] == normalized
    assert _step("execute", "resolve", "resolve")["env"]["REGISTRY"] == normalized
    assert execute["execute"]["env"]["REGISTRY"] == normalized
    assert _step("execute", "execute", "Authenticate to GHCR")["env"]["REGISTRY"] == normalized
    assert _step("execute", "execute", "Re-verify cosign signatures before promotion")["env"][
        "REGISTRY"
    ] == normalized
    assert _step("execute", "execute", "Promote digests to target tags")["env"]["REGISTRY"] == normalized

    for workflow in WORKFLOWS:
        assert WORKFLOWS[workflow].read_text().count("inputs.registry") == 1
