#!/usr/bin/env python3
"""Reject implementation-time self references that depend on a caller workspace."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEARCH_ROOTS = (ROOT / ".github", ROOT / "bootc-build", ROOT / "actions")
SELF_REFERENCE = re.compile(r"^\s*uses:\s*(?:projectbluefin/actions/|\./)")


def workflow_files() -> list[Path]:
    """Return implementation YAML files, including hidden .github files."""
    return sorted(
        path
        for root in SEARCH_ROOTS
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    )


def find_invalid_references() -> list[str]:
    """Find active qualified or workspace-relative self references."""
    failures: list[str] = []
    for path in workflow_files():
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if SELF_REFERENCE.search(line):
                failures.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")
    return failures


def main() -> int:
    failures = find_invalid_references()
    if failures:
        print("Invalid caller-workspace self references found:")
        print("\n".join(failures))
        return 1
    print("Self-repository references use $/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
