"""CLI regression tests for scripts/check-consumer-contract.py."""

import shutil
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_PATH = (
    Path(__file__).parent.parent / "scripts" / "check-consumer-contract.py"
)


def _copy_script(tmp_path: Path) -> Path:
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True)
    dest = script_dir / "check-consumer-contract.py"
    shutil.copy2(SCRIPT_PATH, dest)
    return dest


def _write_composite_action(tmp_path: Path, action_name: str, inputs: list[str]) -> None:
    action_dir = tmp_path / "bootc-build" / action_name
    action_dir.mkdir(parents=True)
    inputs_block = "\n".join(f"  {name}:\n    required: false" for name in inputs)
    (action_dir / "action.yml").write_text(
        f"name: {action_name}\n"
        f"inputs:\n{inputs_block}\n"
        "runs:\n"
        "  using: composite\n"
        "  steps: []\n"
    )


def _write_contract(tmp_path: Path, contract: dict) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "consumer-contract.yml").write_text(yaml.dump(contract))


def _run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_missing_contract_file_exits_1(tmp_path):
    script = _copy_script(tmp_path)

    result = _run_script(script)

    assert result.returncode == 1
    assert "contract file not found" in result.stderr


def test_cli_verbose_success_path(tmp_path):
    script = _copy_script(tmp_path)
    _write_composite_action(tmp_path, "sign-and-publish", ["image-name"])
    _write_contract(
        tmp_path,
        {
            "composite_actions": {
                "sign-and-publish": {
                    "path": "bootc-build/sign-and-publish/action.yml",
                    "required_inputs": ["image-name"],
                }
            }
        },
    )

    result = _run_script(script, "--verbose")

    assert result.returncode == 0
    assert "Checking consumer contract" in result.stdout
    assert "OK  composite_actions/sign-and-publish" in result.stdout
    assert "Consumer contract OK" in result.stdout


def test_cli_validation_failure_exits_1(tmp_path):
    script = _copy_script(tmp_path)
    _write_composite_action(tmp_path, "sign-and-publish", ["other-input"])
    _write_contract(
        tmp_path,
        {
            "composite_actions": {
                "sign-and-publish": {
                    "path": "bootc-build/sign-and-publish/action.yml",
                    "required_inputs": ["image-name"],
                }
            }
        },
    )

    result = _run_script(script)

    assert result.returncode == 1
    assert "Consumer contract violations detected" in result.stderr
    assert "required input 'image-name' missing" in result.stderr


def test_cli_import_failure_without_pyyaml(tmp_path):
    script = _copy_script(tmp_path)

    result = subprocess.run(
        [sys.executable, "-S", str(script)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "PyYAML not installed" in result.stderr
