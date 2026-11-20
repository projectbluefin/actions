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


def _write_reusable_workflow(tmp_path: Path, body: str) -> None:
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    (d / "reusable-build.yml").write_text(
        "on:\n  workflow_call:\n" + body + "jobs: {}\n"
    )


def _write_contract_dict(tmp_path: Path, contract: dict) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "consumer-contract.yml").write_text(yaml.dump(contract))


def test_cli_composite_absent_inputs_fails(tmp_path):
    # Issue #771: a composite action that declares no inputs must still fail
    # when the snapshot requires one.
    script = _copy_script(tmp_path)
    action_dir = tmp_path / "bootc-build" / "example"
    action_dir.mkdir(parents=True)
    (action_dir / "action.yml").write_text(
        "name: example\nruns:\n  using: composite\n  steps: []\n"
    )
    _write_contract_dict(tmp_path, {
        "composite_actions": {
            "example": {"path": "bootc-build/example/action.yml", "required_inputs": ["must-keep"]}
        }
    })

    result = _run_script(script)

    assert result.returncode == 1
    assert "required input 'must-keep' missing" in result.stderr


def test_cli_workflow_null_inputs_fails(tmp_path):
    # Issue #771: a reusable workflow with a null inputs block must fail too.
    script = _copy_script(tmp_path)
    _write_reusable_workflow(tmp_path, "    inputs:\n")
    _write_contract_dict(tmp_path, {
        "reusable_workflow": {
            "path": ".github/workflows/reusable-build.yml", "required_inputs": ["must-keep"]
        }
    })

    result = _run_script(script)

    assert result.returncode == 1
    assert "required input 'must-keep' missing" in result.stderr


def test_cli_zero_required_inputs_passes_with_empty_live(tmp_path):
    # An interface the snapshot requires nothing of keeps passing.
    script = _copy_script(tmp_path)
    action_dir = tmp_path / "bootc-build" / "example"
    action_dir.mkdir(parents=True)
    (action_dir / "action.yml").write_text(
        "name: example\nruns:\n  using: composite\n  steps: []\n"
    )
    _write_contract_dict(tmp_path, {
        "composite_actions": {
            "example": {"path": "bootc-build/example/action.yml", "required_inputs": []}
        }
    })

    result = _run_script(script)

    assert result.returncode == 0
    assert "Consumer contract OK" in result.stdout


def test_cli_verbose_identifies_missing_input(tmp_path):
    # Issue #771: verbose CLI must also exit nonzero and name the input.
    script = _copy_script(tmp_path)
    action_dir = tmp_path / "bootc-build" / "example"
    action_dir.mkdir(parents=True)
    (action_dir / "action.yml").write_text(
        "name: example\nruns:\n  using: composite\n  steps: []\n"
    )
    _write_contract_dict(tmp_path, {
        "composite_actions": {
            "example": {"path": "bootc-build/example/action.yml", "required_inputs": ["must-keep"]}
        }
    })

    result = _run_script(script, "--verbose")

    assert result.returncode == 1
    assert "required input 'must-keep' missing" in result.stderr


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
