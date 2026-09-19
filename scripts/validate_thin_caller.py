#!/usr/bin/env python3
"""
Check workflows that act as thin-callers: any workflow file that references
reusable workflows in projectbluefin/actions should be "thin" (short).

This script searches the repository for YAML files under .github/workflows,
finds those that contain a `uses:` referencing `projectbluefin/actions`, and
ensures their non-empty, non-comment line count is <= max_lines.

Exit 0 on success, non-zero (1) on violation.
"""
import argparse
import fnmatch
import os
from pathlib import Path
import re
import sys

REUSABLE_REQUIRES_PATTERN = re.compile(
    r"^\s*#\s*requires:\s*(PAT|App-token|any)(?:\|(PAT|App-token|any))*\s*$"
)


def count_effective_lines(path):
    """Count non-blank, non-comment lines in a file."""
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                continue
            count += 1
    return count


def file_uses_projectbluefin(path):
    """Return True if file contains a uses: reference to projectbluefin/actions."""
    pattern = re.compile(r"uses:\s*projectbluefin/actions(?:/|@|$)")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if pattern.search(line):
                return True
    return False


def find_workflows(root_dir):
    """Find all workflow YAML files under root_dir/.github/workflows."""
    workflows_dir = Path(root_dir) / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    return sorted(
        str(p) for p in workflows_dir.glob("*") if p.is_file() and p.suffix in {".yml", ".yaml"}
    )


def find_reusable_workflows(root_dir):
    """Find all reusable workflow YAML files under root_dir/.github/workflows."""
    workflows_dir = Path(root_dir) / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    return sorted(
        str(p)
        for p in workflows_dir.glob("reusable-*.yml")
        if p.is_file()
    ) + sorted(
        str(p)
        for p in workflows_dir.glob("reusable-*.yaml")
        if p.is_file()
    )


def get_reusable_requires_annotation(path):
    """Return the '# requires: ...' annotation token type for a reusable workflow, or None if missing."""
    with open(path, "r", encoding="utf-8") as f:
        in_workflow_call = False
        for line in f:
            stripped = line.strip()
            if stripped.startswith("workflow_call:"):
                in_workflow_call = True
                continue
            if in_workflow_call:
                if line and not line[0].isspace() and not stripped.startswith("#"):
                    break
                m = REUSABLE_REQUIRES_PATTERN.match(line)
                if m:
                    return stripped.split("requires:", 1)[1].strip()
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--max-lines", type=int, default=50, help="Maximum allowed effective lines for thin callers")
    p.add_argument("--root", default=".", help="Repository root to search")
    p.add_argument(
        "--check-reusable-requires",
        action="store_true",
        help="Validate that reusable-*.yml workflows have a '# requires:' token annotation",
    )
    args = p.parse_args()

    if args.check_reusable_requires:
        reusables = find_reusable_workflows(args.root)
        if not reusables:
            print("No reusable workflow files found under .github/workflows/; nothing to check.")
            return 0
        missing = []
        for wf in reusables:
            ann = get_reusable_requires_annotation(wf)
            if not ann:
                missing.append(wf)
        if missing:
            print("Reusable workflow token annotation violations found:\n")
            for wf in missing:
                print(f"  - {wf}: missing valid '# requires: PAT|App-token|any' annotation under workflow_call:")
            return 1
        print(f"All {len(reusables)} reusable workflows have valid token requirement annotations.")
        return 0

    workflows = find_workflows(args.root)
    if not workflows:
        print("No workflow files found under .github/workflows/; nothing to check.")
        return 0

    violations = []
    for wf in sorted(workflows):
        try:
            if not file_uses_projectbluefin(wf):
                continue
        except Exception as e:
            print(f"Skipping {wf}: error reading file: {e}")
            continue
        lines = count_effective_lines(wf)
        if lines > args.max_lines:
            violations.append((wf, lines))

    if violations:
        print("Thin-caller contract violations found:\n")
        for wf, lines in violations:
            print(f"  - {wf}: {lines} effective lines (max {args.max_lines})")
        print("\nPolicy: Caller workflows that delegate to projectbluefin/actions must be thin callers (default max 50 effective lines).\nPlease extract logic into reusable workflows in projectbluefin/actions and keep callers small.")
        return 1

    print("All caller workflows pass the thin-caller size gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
