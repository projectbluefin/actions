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
import re
import sys


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


def find_workflows(root_dir, glob_pattern=".github/workflows/*.yml"):
    matches = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for name in filenames:
            if fnmatch.fnmatch(os.path.join(dirpath, name), glob_pattern):
                matches.append(os.path.join(dirpath, name))
    return matches


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--max-lines", type=int, default=50, help="Maximum allowed effective lines for thin callers")
    p.add_argument("--root", default=".", help="Repository root to search")
    args = p.parse_args()

    root = args.root
    workflows = find_workflows(root, os.path.join(".github", "workflows", "*.yml"))
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
