"""upgrade-test.yml boots a previous pinned build and upgrades to the candidate (#753).

Without `previous_image` the lifecycle suite boots `image` and upgrades to
itself, which testsuite's no-op guard fails. These tests run the shipped
`plan` step script under bash and check the `e2e.yml` wiring.
"""
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/upgrade-test.yml"
CANDIDATE = "ghcr.io/org/img@sha256:" + "b" * 64
PREVIOUS = "ghcr.io/org/img@sha256:" + "a" * 64


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _plan(tmp_path, image, previous):
    script = _workflow()["jobs"]["plan"]["steps"][0]["run"]
    out = tmp_path / "out"
    out.write_text("")
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                            env={"IMAGE": image, "PREVIOUS_IMAGE": previous,
                                 "GITHUB_OUTPUT": str(out), "PATH": "/usr/bin:/bin"})
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return result, outputs


def test_previous_image_boots_first_and_stages_the_candidate(tmp_path):
    result, outputs = _plan(tmp_path, CANDIDATE, PREVIOUS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs == {"boot_image": PREVIOUS, "target_image": CANDIDATE}


def test_tagged_candidate_and_pinned_previous_from_the_same_repo(tmp_path):
    result, outputs = _plan(tmp_path, "ghcr.io/org/img:testing", PREVIOUS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs["boot_image"] == PREVIOUS


def test_empty_previous_keeps_todays_behaviour(tmp_path):
    result, outputs = _plan(tmp_path, CANDIDATE, "")
    assert result.returncode == 0
    assert outputs == {"boot_image": CANDIDATE, "target_image": ""}


@pytest.mark.parametrize("previous,message", [
    ("ghcr.io/org/img:testing-20261101-abc1234", "digest-pinned"),
    (CANDIDATE, "equals image"),
    ("ghcr.io/other/img@sha256:" + "a" * 64, "same repository"),
])
def test_unusable_previous_image_fails_before_booting(tmp_path, previous, message):
    result, _ = _plan(tmp_path, CANDIDATE, previous)
    assert result.returncode != 0
    assert message in result.stdout


def test_registry_port_is_not_mistaken_for_a_tag(tmp_path):
    image = "localhost:5000/img@sha256:" + "b" * 64
    previous = "localhost:5000/img@sha256:" + "a" * 64
    result, outputs = _plan(tmp_path, image, previous)
    assert result.returncode == 0, result.stdout
    assert outputs["target_image"] == image


def test_e2e_call_uses_the_planned_images():
    wf = _workflow()
    for trigger in ("workflow_call", "workflow_dispatch"):
        assert "previous_image" in wf[True][trigger]["inputs"]
    job = wf["jobs"]["upgrade-test"]
    assert job["needs"] == "plan"
    assert job["with"]["image"] == "${{ needs.plan.outputs.boot_image }}"
    assert job["with"]["target-image"] == "${{ needs.plan.outputs.target_image }}"
    assert wf["jobs"]["plan"]["permissions"] == {}
