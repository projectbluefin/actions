"""factory-drift.yml Check 2 matcher (issue #785).

Consumers may reference projectbluefin/actions as `@v1` or as a full SHA with a
trailing `# v1` comment that Renovate keeps current. Only a bare SHA with no
version comment is drift.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_actions_sha_pins.py"
SHA = "03d9862e" + "0" * 32


def _run(root):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def _snapshot(tmp_path, *uses_lines):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    body = "jobs:\n  build:\n    steps:\n" + "".join(f"      {line}\n" for line in uses_lines)
    (wf_dir / "build.yml").write_text(body)
    return tmp_path


def test_commented_sha_pin_is_not_flagged(tmp_path):
    root = _snapshot(tmp_path, f"- uses: projectbluefin/actions/bootc-build/chunka@{SHA} # v1")
    result = _run(root)
    assert result.returncode == 0, result.stdout
    assert result.stdout == ""


def test_bare_sha_pin_is_flagged(tmp_path):
    root = _snapshot(tmp_path, f"- uses: projectbluefin/actions/bootc-build/chunka@{SHA}")
    result = _run(root)
    assert result.returncode == 1
    assert f".github/workflows/build.yml:4: - uses: projectbluefin/actions/bootc-build/chunka@{SHA}" in result.stdout


def test_v1_tag_is_not_flagged(tmp_path):
    root = _snapshot(tmp_path, "- uses: projectbluefin/actions/bootc-build/chunka@v1")
    result = _run(root)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "line",
    [
        f"uses: projectbluefin/actions/.github/workflows/reusable-build.yml@{SHA}  #v1",
        f"- uses: 'projectbluefin/actions/bootc-build/chunka@{SHA}' # v1.4.0",
        f"- uses: projectbluefin/actions/bootc-build/chunka@{SHA} # v2",
        f"# - uses: projectbluefin/actions/bootc-build/chunka@{SHA}",
    ],
)
def test_other_accepted_forms(tmp_path, line):
    assert _run(_snapshot(tmp_path, line)).returncode == 0


@pytest.mark.parametrize(
    "line",
    [
        f"- uses: projectbluefin/actions/bootc-build/chunka@{SHA} # pinned",
        f"- uses: projectbluefin/actions/bootc-build/chunka@{SHA} # v",
    ],
)
def test_comment_without_version_is_flagged(tmp_path, line):
    assert _run(_snapshot(tmp_path, line)).returncode == 1


def test_mixed_snapshot_reports_only_the_bare_pin(tmp_path):
    root = _snapshot(
        tmp_path,
        f"- uses: projectbluefin/actions/bootc-build/chunka@{SHA} # v1",
        f"- uses: projectbluefin/actions/bootc-build/push-image@{SHA}",
        "- uses: projectbluefin/actions/bootc-build/rechunk@v1",
    )
    result = _run(root)
    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f".github/workflows/build.yml:5: - uses: projectbluefin/actions/bootc-build/push-image@{SHA}"
    ]


def test_missing_root_is_an_error_not_a_clean_pass(tmp_path):
    assert _run(tmp_path / "absent").returncode == 2
