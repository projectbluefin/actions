"""Exercise the shipped apt cache helper without root or access to Ubuntu mirrors."""
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bootc-build/setup-runner/apt-cache.sh"
ACTION = ROOT / "bootc-build/setup-runner/action.yml"


@pytest.fixture
def runner(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    system = tmp_path / "system"
    for folder in ("var/cache/apt/archives", "var/lib/apt/lists"):
        path = system / folder
        path.mkdir(parents=True)
        (path / "lock").touch(mode=0o000)
        (path / "partial").mkdir(mode=0o000)
        (path / "auxfiles").mkdir(mode=0o000)
    sudo = bin_dir / "sudo"
    sudo.write_text('''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as f:
    f.write(json.dumps(args) + "\\n")
args = [os.environ["SYSTEM"] + a if a.startswith(("/var/", "/etc/")) else a for a in args]
if args[0] == "apt":
    if "--no-download" in args and os.environ.get("FAIL_CACHE") == "true":
        sys.exit(1)
    if "update" in args and os.environ.get("FAIL_UPDATE") == "true":
        sys.exit(1)
    if "install" in args and "--no-download" not in args:
        root = pathlib.Path(os.environ["SYSTEM"])
        (root / "var/cache/apt/archives/tool.deb").write_text("package")
        (root / "var/lib/apt/lists/mirror_Packages").write_text("index")
    sys.exit(0)
sys.exit(subprocess.call(args))
''')
    sudo.chmod(0o755)
    for tool in ("podman", "buildah", "crun", "skopeo"):
        executable = bin_dir / tool
        executable.write_text(f"#!/bin/sh\necho '{tool} version test'\n")
        executable.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               SYSTEM=str(system), CALL_LOG=str(tmp_path / "calls"),
               GITHUB_OUTPUT=str(tmp_path / "output"), APT_MODE="native",
               APT_PACKAGES="qemu-system-x86", APT_CACHE_HIT="false",
               APT_CACHE_DIR=str(tmp_path / "stage"), ImageOS="ubuntu24",
               ImageVersion="20261111.1", RUNNER_OS="Linux", RUNNER_ARCH="X64")

    def run(command="install", **overrides):
        return subprocess.run(["bash", str(SCRIPT), command],
                              env=dict(env, **overrides), capture_output=True, text=True)

    def calls():
        path = Path(env["CALL_LOG"])
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    yield env, run, calls
    # Restore access before pytest removes its temporary tree (older pytest
    # versions cannot clean up mode-000 directories without this).
    for folder in ("var/cache/apt/archives", "var/lib/apt/lists"):
        for name in ("partial", "auxfiles"):
            (system / folder / name).chmod(0o700)
        (system / folder / "lock").chmod(0o600)


def test_miss_stages_only_packages_and_lists_owned_by_runner(runner):
    env, run, calls = runner
    result = run()
    assert result.returncode == 0, result.stderr
    stage = Path(env["APT_CACHE_DIR"])
    assert sorted(str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file()) == [
        "archives/tool.deb", "lists/mirror_Packages"]
    assert all(p.stat().st_uid == os.getuid() for p in stage.rglob("*"))
    assert any(c[0] == "chown" for c in calls())
    installs = [c for c in calls() if c[0] == "apt" and "install" in c]
    assert len(installs) == 1
    assert "--no-install-recommends" in installs[0]
    for option in ("Acquire::Retries=5", "Acquire::http::Timeout=60",
                   "Acquire::https::Timeout=60", "Binary::apt::APT::Keep-Downloaded-Packages=true"):
        assert option in installs[0]


@pytest.mark.parametrize("mode", ["native", "resolute"])
def test_hit_restores_files_without_update_or_download(runner, mode):
    env, run, calls = runner
    assert run(APT_MODE=mode).returncode == 0
    Path(env["CALL_LOG"]).unlink()
    for path in ("var/cache/apt/archives/tool.deb", "var/lib/apt/lists/mirror_Packages"):
        (Path(env["SYSTEM"]) / path).unlink()
    result = run(APT_MODE=mode, APT_CACHE_HIT="true", FAIL_UPDATE="true")
    assert result.returncode == 0, result.stderr
    apt = [c for c in calls() if c[0] == "apt"]
    assert len(apt) == 1
    assert "--no-download" in apt[0]
    assert not any("update" in c for c in apt)
    assert (Path(env["SYSTEM"]) / "var/lib/apt/lists/mirror_Packages").read_text() == "index"
    assert not any(c[0] == "chown" for c in calls())
    if mode == "resolute":
        assert "podman/resolute" in apt[0]
        assert "--allow-downgrades" in apt[0]
        assert "skopeo version test" in result.stdout
        assert not (Path(env["SYSTEM"]) / "etc/needrestart/conf.d/99-no-restarts.conf").exists()


@pytest.mark.parametrize("missing", [False, True])
def test_unusable_cache_falls_back_to_update_and_install(runner, missing):
    env, run, calls = runner
    if not missing:
        assert run().returncode == 0
        Path(env["CALL_LOG"]).unlink()
    result = run(APT_CACHE_HIT="true", FAIL_CACHE="true")
    assert result.returncode == 0, result.stderr
    assert "refreshing from Ubuntu mirrors" in result.stdout
    apt = [c for c in calls() if c[0] == "apt"]
    assert "update" in apt[-2]
    assert "install" in apt[-1] and "--no-download" not in apt[-1]


def test_real_mirror_failure_is_fatal_and_cleans_needrestart(runner):
    env, run, _ = runner
    result = run(APT_MODE="resolute", FAIL_UPDATE="true")
    assert result.returncode != 0
    assert not (Path(env["SYSTEM"]) / "etc/needrestart/conf.d/99-no-restarts.conf").exists()


def test_key_is_sorted_and_changes_with_packages_image_arch_and_mode(runner):
    env, run, _ = runner

    def key(**kwargs):
        Path(env["GITHUB_OUTPUT"]).unlink(missing_ok=True)
        assert run("key", **kwargs).returncode == 0
        return Path(env["GITHUB_OUTPUT"]).read_text().strip()

    original = key(APT_PACKAGES="skopeo qemu-system-x86")
    assert original.startswith("key=apt-pkgs-ubuntu24-X64-20261111.1-")
    assert original == key(APT_PACKAGES="qemu-system-x86 skopeo skopeo")
    assert original != key(APT_PACKAGES="skopeo")
    for overrides in ({"ImageVersion": "next"}, {"ImageOS": "ubuntu26"},
                      {"RUNNER_ARCH": "ARM64"}, {"APT_MODE": "resolute"}):
        assert original != key(APT_PACKAGES="skopeo qemu-system-x86", **overrides)


@pytest.mark.parametrize("packages", ["--help", "skopeo/resolute", "qemu;id", "$(id)"])
def test_package_input_cannot_be_options_or_commands(runner, packages):
    _, run, calls = runner
    assert run("key", APT_PACKAGES=packages).returncode != 0
    assert calls() == []


def test_action_wiring_separates_native_and_resolute_caches():
    action = yaml.safe_load(ACTION.read_text())
    assert action["inputs"]["apt-packages"]["default"] == ""
    steps = action["runs"]["steps"]
    native_install = next(i for i, s in enumerate(steps) if s["name"] == "Install native Ubuntu packages")
    source = next(i for i, s in enumerate(steps) if s["name"] == "Select podman source")
    assert native_install < source
    for mode, folder in (("native", "apt-native-cache"), ("resolute", "apt-resolute-cache")):
        install = next(s for s in steps if s.get("env", {}).get("APT_MODE") == mode
                       and s.get("run", "").endswith('install'))
        assert install["run"] == 'bash "$GITHUB_ACTION_PATH/apt-cache.sh" install'
        assert "cache-hit" in install["env"]["APT_CACHE_HIT"]
        cache_steps = [s for s in steps if s.get("with", {}).get("path") == '${{ runner.temp }}/' + folder]
        assert len(cache_steps) == 2
        assert cache_steps[0]["with"]["key"] == cache_steps[1]["with"]["key"]
        assert "restore-keys" not in cache_steps[0]["with"]
        if mode == "native":
            assert install["if"] == "inputs.apt-packages != ''"
        else:
            assert install["if"] == "steps.podman-source.outputs.install-from-resolute == 'true'"
