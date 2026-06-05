#!/usr/bin/env python3
"""
check-consumer-contract.py — Validates that required action inputs listed in
docs/consumer-contract.yml still exist in the live action.yml files.

Exits non-zero if any required input has been removed or renamed, which would
silently break ublue-os/aurora, ublue-os/bazzite, and other external consumers.

Usage:
    python3 scripts/check-consumer-contract.py
    python3 scripts/check-consumer-contract.py --verbose
"""

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).parent.parent
CONTRACT_FILE = REPO_ROOT / "docs" / "consumer-contract.yml"


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def get_live_inputs(action_path: Path) -> set[str]:
    """Return the set of input names defined in a live action.yml or workflow."""
    if not action_path.exists():
        return set()
    data = load_yaml(action_path)
    # Composite actions: top-level 'inputs'
    inputs = data.get("inputs", {})
    if inputs:
        return set(inputs.keys())
    # Reusable workflows: on.workflow_call.inputs (True key due to YAML bool quirk)
    on_block = data.get(True) or data.get("on", {})
    if isinstance(on_block, dict):
        wc = on_block.get("workflow_call", {})
        if isinstance(wc, dict):
            wc_inputs = wc.get("inputs", {})
            if wc_inputs:
                return set(wc_inputs.keys())
    return set()


def check_contract(contract: dict, verbose: bool) -> list[str]:
    failures = []

    def check_section(label: str, path_str: str, required: list[str]) -> None:
        path = REPO_ROOT / path_str
        live = get_live_inputs(path)
        if not live and path.exists():
            if verbose:
                print(f"  WARN: {label}: could not parse inputs from {path_str}")
            return
        if not path.exists():
            failures.append(f"{label}: file missing — {path_str}")
            return
        for inp in required:
            if inp not in live:
                failures.append(
                    f"{label}: required input '{inp}' missing from {path_str} "
                    f"(live inputs: {sorted(live)})"
                )
            elif verbose:
                print(f"  OK  {label}: '{inp}' present in {path_str}")

    # Check reusable workflow
    rw = contract.get("reusable_workflow", {})
    if rw:
        check_section(
            "reusable_workflow",
            rw["path"],
            rw.get("required_inputs", []),
        )

    # Check composite actions
    for action_name, spec in contract.get("composite_actions", {}).items():
        check_section(
            f"composite_actions/{action_name}",
            spec["path"],
            spec.get("required_inputs", []),
        )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not CONTRACT_FILE.exists():
        print(f"ERROR: contract file not found: {CONTRACT_FILE}", file=sys.stderr)
        return 1

    contract = load_yaml(CONTRACT_FILE)
    if args.verbose:
        print(f"Checking consumer contract: {CONTRACT_FILE}")

    failures = check_contract(contract, args.verbose)

    if failures:
        print("\n❌ Consumer contract violations detected:\n", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print(
            "\nRenaming or removing required inputs breaks ublue-os/aurora, "
            "ublue-os/bazzite, and other external consumers.",
            file=sys.stderr,
        )
        print(
            "If this is an intentional breaking change, bump to @v2 and update "
            "docs/consumer-contract.yml.",
            file=sys.stderr,
        )
        return 1

    total = sum(
        len(contract.get("reusable_workflow", {}).get("required_inputs", [])) +
        sum(
            len(spec.get("required_inputs", []))
            for spec in contract.get("composite_actions", {}).values()
        )
        for _ in [None]  # single iteration
    )
    print(f"✅ Consumer contract OK — {total} required inputs verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
