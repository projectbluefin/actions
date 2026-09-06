"""Guard: vendored trust material must have a verifier that consumes it.

`keys/` once held three vendored cosign public keys (fedora-ostree,
projectbluefin-common, ublue-os-brew) that no code path in this repository or
anywhere in the org ever read. Every verification site here is keyless
(Sigstore/Fulcio + --certificate-identity-regexp), so the keys guarded nothing
while a weekly workflow filed priority/p1 security issues about them.

This test keeps that shape from coming back: any committed public-key file must
be referenced by something other than a watchdog that merely diffs it against
its own upstream URL. If key-based verification is genuinely reintroduced, it
must land together with the call site that uses it, which satisfies this guard
naturally.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

KEY_SUFFIXES = (".pub", ".pem", ".gpg", ".asc")

# Directories that hold third-party or non-source content and would produce
# noise rather than signal.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache"}

# A reference from one of these files does not count as a consumer: they only
# re-state the key's own location for rotation/monitoring purposes.
WATCHDOG_NAME_RE = re.compile(r"(rotation|drift|health)", re.IGNORECASE)


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    paths = (REPO_ROOT / p for p in out.split("\0") if p)
    # git ls-files reports index entries, which can include files already
    # deleted from the working tree. Only judge what is actually present.
    return [p for p in paths if p.is_file()]


def _key_files(tracked: list[Path]) -> list[Path]:
    return [p for p in tracked if p.suffix in KEY_SUFFIXES]


def _searchable_files(tracked: list[Path]) -> list[Path]:
    result = []
    for path in tracked:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in KEY_SUFFIXES:
            continue
        result.append(path)
    return result


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def test_every_vendored_key_has_a_non_watchdog_consumer():
    """Each committed key file must be read by real code, not only watched."""
    tracked = _tracked_files()
    keys = _key_files(tracked)
    if not keys:
        return

    searchable = _searchable_files(tracked)
    contents = {p: _read(p) for p in searchable}

    orphans = {}
    for key in keys:
        rel = key.relative_to(REPO_ROOT).as_posix()
        needles = (rel, key.name)
        consumers = [
            p.relative_to(REPO_ROOT).as_posix()
            for p, text in contents.items()
            if any(n in text for n in needles)
            and not WATCHDOG_NAME_RE.search(p.name)
        ]
        if not consumers:
            orphans[rel] = sorted(
                p.relative_to(REPO_ROOT).as_posix()
                for p, text in contents.items()
                if any(n in text for n in needles)
            )

    assert not orphans, (
        "Vendored key files have no consumer outside rotation/drift watchdogs: "
        f"{orphans}. A key that is only compared against its own upstream URL "
        "protects nothing while still paging maintainers "
        "(see projectbluefin/actions#441)."
    )
