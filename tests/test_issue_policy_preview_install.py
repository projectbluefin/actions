"""Exercise parser installation for both current and older preview runtimes."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("has_lock", [True, False])
def test_preview_parser_install_uses_trusted_hashes(tmp_path, has_lock):
    workflow = yaml.safe_load((ROOT / ".github/workflows/reusable-issue-policy-preview.yml").read_text())
    steps = workflow["jobs"]["preview"]["steps"]
    script = next(step["run"] for step in steps if step["name"] == "Install data parser without caller dependency files")
    runtime = tmp_path / "actions-source/scripts"
    runtime.mkdir(parents=True)
    if has_lock:
        (runtime / "requirements.txt").write_text("trusted runtime lock\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    fake_python = binary / "python3"
    fake_python.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$RUNNER_TEMP/args"\ncat "${@: -1}" > "$RUNNER_TEMP/installed"\n')
    fake_python.chmod(0o755)
    env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path)}
    subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env, check=True)
    args = (tmp_path / "args").read_text().splitlines()
    assert "--require-hashes" in args
    installed = (tmp_path / "installed").read_text()
    if has_lock:
        assert args[-1] == "actions-source/scripts/requirements.txt"
        assert installed == "trusted runtime lock\n"
    else:
        assert "--no-binary=pyyaml" in args
        package, digest = installed.strip().split(" --hash=sha256:")
        lock = (ROOT / "scripts/requirements.txt").read_text()
        assert package == "pyyaml==6.0.3"
        assert package + " \\" in lock
        assert "--hash=sha256:" + digest in lock
