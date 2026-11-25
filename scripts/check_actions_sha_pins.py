#!/usr/bin/env python3
"""Find consumer pins of projectbluefin/actions that name no version.

factory-drift.yml Check 2 runs this against each consumer's fetched workflow
snapshot. Two reference forms are accepted:

* the managed floating tag, ``projectbluefin/actions/...@v1``;
* a full 40-hex commit SHA followed on the same line by a version comment,
  ``projectbluefin/actions/...@<sha> # v1``. Renovate's digest updates read
  that comment to know which tag the pin tracks, and consumers (common's
  ``build.yml``) document this form as a deliberate choice.

A bare SHA pin with no version comment is reported: nothing records which tag
it is meant to follow, so Renovate cannot keep it current.

Comment lines are ignored. Exit codes: 0 = no bare pins, 1 = bare pins found
(one ``path:line: text`` per finding on stdout), 2 = bad usage.
"""
import argparse
import re
import sys
from pathlib import Path

SHA_PIN = re.compile(
    r"""uses:\s*["']?projectbluefin/actions(?:/[^@\s"']*)?@[0-9a-f]{40}["']?(?P<rest>.*)$"""
)
# `# v1`, `# v2`, or a full release such as `# v1.4.0`.
VERSION_COMMENT = re.compile(r"^\s+#\s*v\d+(?:\.\d+)*\b")


def is_bare_sha_pin(line):
    """Return True if ``line`` pins projectbluefin/actions to a SHA with no
    trailing version comment."""
    if line.lstrip().startswith("#"):
        return False
    match = SHA_PIN.search(line)
    if match is None:
        return False
    return VERSION_COMMENT.match(match.group("rest")) is None


def find_bare_sha_pins(root):
    """Yield ``(path, line_number, line)`` for every bare SHA pin under root."""
    files = sorted(
        p for p in Path(root).rglob("*") if p.is_file() and p.suffix in (".yml", ".yaml")
    )
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            for number, line in enumerate(f, start=1):
                if is_bare_sha_pin(line):
                    yield path, number, line.rstrip("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="directory to scan recursively")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: --root {root} is not a directory", file=sys.stderr)
        return 2

    findings = list(find_bare_sha_pins(root))
    for path, number, line in findings:
        print(f"{path.relative_to(root)}:{number}: {line.strip()}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
