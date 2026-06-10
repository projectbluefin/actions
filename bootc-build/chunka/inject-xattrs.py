#!/usr/bin/env python3
"""inject-xattrs.py — set user.component xattrs from a fakecap TSV manifest.

Used by the bootc-build/chunka composite action (BST path) to physically write
user.component and user.update-interval xattrs onto a writable overlay before
chunkah scans it.

chunkah uses rustix raw syscalls for xattr reads (bypassing libc / LD_PRELOAD),
so xattrs must be physically present on the filesystem. See coreos/chunkah#113
(closed — physical xattr injection is the confirmed resolution).

Usage:
    sudo python3 inject-xattrs.py <manifest.tsv> <rootfs>

Manifest format (TSV, one entry per line):
    /usr/bin/foo  <TAB>  element/name.bst  <TAB>  weekly
"""
from __future__ import annotations
import os
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <manifest.tsv> <rootfs>", file=sys.stderr)
        return 1

    manifest_path, rootfs = sys.argv[1], sys.argv[2]
    ok = skip = 0

    with open(manifest_path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            rel_path, component = parts[0], parts[1]
            interval = parts[2] if len(parts) > 2 else "weekly"
            target = rootfs + rel_path
            try:
                os.setxattr(
                    target,
                    b"user.component",
                    component.encode(),
                    follow_symlinks=False,
                )
                os.setxattr(
                    target,
                    b"user.update-interval",
                    interval.encode(),
                    follow_symlinks=False,
                )
                ok += 1
            except OSError:
                skip += 1

    print(f"xattrs: {ok} set, {skip} skipped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
