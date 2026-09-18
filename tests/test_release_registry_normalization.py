"""Regression coverage for OCI registry canonicalization in release reusables."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).parent.parent

# Siblings that canonicalize a caller-supplied `registry` prefix.
WORKFLOWS = {
    "promote": REPO_ROOT / ".github/workflows/reusable-promote-squash.yml",
    "gate": REPO_ROOT / ".github/workflows/reusable-release-gate.yml",
    "execute": REPO_ROOT / ".github/workflows/reusable-execute-release.yml",
}

# `reusable-release.yml` takes a full `image` reference instead of a `registry`
# prefix, so it carries its own normalization job under a different output name.
IMAGE_WORKFLOWS = {
    "release": REPO_ROOT / ".github/workflows/reusable-release.yml",
}

ALL_WORKFLOWS = {**WORKFLOWS, **IMAGE_WORKFLOWS}


def _workflow(name):
    return yaml.safe_load(ALL_WORKFLOWS[name].read_text())


def _step(workflow, job, identifier):
    return next(
        step
        for step in _workflow(workflow)["jobs"][job]["steps"]
        if step.get("id") == identifier or step.get("name") == identifier
    )


def _normalize_output(workflow, job, input_env, value, output_key, tmp_path):
    output = tmp_path / f"{workflow}-{output_key}"
    completed = subprocess.run(
        ["bash", "-c", _step(workflow, job, "normalize")["run"]],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GITHUB_OUTPUT": str(output),
            input_env: value,
        },
    )
    assert completed.stderr == ""
    return output.read_text().strip().removeprefix(f"{output_key}=")


def _normalized_registry(workflow, input_registry, tmp_path):
    return _normalize_output(
        workflow, "normalize-registry", "INPUT_REGISTRY", input_registry, "registry", tmp_path
    )


def _normalized_image(workflow, input_image, tmp_path):
    return _normalize_output(
        workflow, "normalize-image", "INPUT_IMAGE", input_image, "image", tmp_path
    )


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


@pytest.mark.parametrize(
    ("input_image", "expected"),
    [
        ("ghcr.io/ExampleOwner/sample-image", "ghcr.io/exampleowner/sample-image"),
        ("ghcr.io/projectbluefin/bluefin", "ghcr.io/projectbluefin/bluefin"),
        ("docker://ghcr.io/ExampleOwner/sample-image", "ghcr.io/exampleowner/sample-image"),
    ],
)
def test_release_normalizes_full_image_reference(input_image, expected, tmp_path):
    """`image` (a full reference) is canonicalized at the same boundary as `registry`."""
    assert _normalized_image("release", input_image, tmp_path) == expected


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


def _write_syft_mock(tmp_path):
    calls = tmp_path / "syft-calls"
    mock_dir = tmp_path / "bin"
    mock_dir.mkdir()
    syft = mock_dir / "syft"
    syft.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$SYFT_CALLS"\n'
        'for arg in "$@"; do\n'
        '  case "${arg}" in spdx-json=*) printf "{}" > "${arg#spdx-json=}" ;;\n'
        "  esac\n"
        "done\n"
    )
    syft.chmod(0o755)
    return mock_dir, calls


def test_release_inline_sbom_scans_normalized_image(tmp_path):
    """Inline Syft is handed the canonicalized reference, never a mixed-case path."""
    image = _normalized_image("release", "ghcr.io/ExampleOwner/sample-image", tmp_path)
    mock_dir, calls = _write_syft_mock(tmp_path)

    subprocess.run(
        ["bash", "-c", _step("release", "image-release", "generate-sbom")["run"]],
        check=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ['PATH']}",
            "SYFT_CALLS": str(calls),
            "IMAGE": image,
            "STREAM_NAME": "stable",
            "IMAGE_NAME": "sample-image",
            "SYFT_CMD": str(mock_dir / "syft"),
        },
    )

    assert calls.read_text() == (
        "registry:ghcr.io/exampleowner/sample-image:stable "
        "--scope squashed --parallelism 1 "
        "--override-default-catalogers rpm-db-cataloger "
        "-o spdx-json=sbom-current/sample-image.sbom.json\n"
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


def test_release_consumers_use_the_normalized_image_output():
    """The image reusable routes every OCI consumer through its normalization job."""
    normalized = "${{ needs.normalize-image.outputs.image }}"
    release = _workflow("release")["jobs"]

    assert release["normalize-image"]["outputs"]["image"] == (
        "${{ steps.normalize.outputs.image }}"
    )
    assert "normalize-image" in release["image-release"]["needs"]
    assert "normalize-image" in release["semver-release"]["needs"]

    assert _step("release", "image-release", "image_name")["env"]["IMAGE"] == normalized
    assert _step("release", "image-release", "digest")["env"]["IMAGE"] == normalized
    assert _step("release", "image-release", "generate-sbom")["env"]["IMAGE"] == normalized
    assert _step("release", "image-release", "Create release")["with"]["image"] == normalized
    assert (
        _step("release", "semver-release", "Append desktop screenshot to release notes")["env"][
            "IMAGE"
        ]
        == normalized
    )


def test_release_confines_raw_image_input_to_preparation_jobs():
    """Raw caller input reaches only mode detection and the normalization job."""
    release = _workflow("release")["jobs"]
    assert IMAGE_WORKFLOWS["release"].read_text().count("${{ inputs.image }}") == 2

    for job_name, job in release.items():
        if job_name in {"validate", "normalize-image"}:
            assert "${{ inputs.image }}" in yaml.safe_dump(job)
        else:
            assert "${{ inputs.image }}" not in yaml.safe_dump(job)
