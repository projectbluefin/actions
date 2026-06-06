#!/usr/bin/env python3
"""
sbom_diff.py — Parse one or two SPDX 2.3 SBOMs and produce versions.json
for use by render_card.py and render_notes.py.

Usage:
    python3 sbom_diff.py \\
        --current  current.spdx.json \\
        [--previous previous.spdx.json] \\
        --notable-packages notable.json \\
        --output   versions.json

notable.json schema — array of objects:
    [{"sbom_name": "linux", "label": "Kernel", "spdxid_filter": "components-linux.bst"},
     {"sbom_name": "gnome-shell", "label": "GNOME"},
     ...]

Output versions.json schema:
{
  "notable": [
    {"name": "Kernel", "version": "6.9.14", "prev": null, "changed": false},
    ...
  ],
  "diff": {
    "changed_count": 12, "added_count": 3, "removed_count": 1,
    "changed": [{"name": "...", "prev": "...", "curr": "..."}],
    "added":   [{"name": "...", "version": "..."}],
    "removed": [{"name": "...", "version": "..."}]
  },
  "has_prev": false,
  "total_packages": 423
}
"""
import argparse
import json
import os
import re
import sys


# ── Version normalisation ─────────────────────────────────────────────────────

_EPOCH_RE  = re.compile(r"^\d+:")
_FC_RE     = re.compile(r"\.fc\d{2}")


def clean_version(raw: str | None) -> str | None:
    if not raw:
        return None
    v = _EPOCH_RE.sub("", raw)
    v = _FC_RE.sub("", v)
    v = v.strip()
    return v or None


def short_sha(raw: str | None) -> str | None:
    if raw and re.match(r"^[0-9a-f]{40,64}$", raw.strip()):
        return raw.strip()[:8]
    return None


def best_version(raw: str | None) -> str | None:
    v = clean_version(raw)
    if v:
        return v
    return short_sha(raw)


def is_semver(v: str | None) -> bool:
    return bool(v and re.match(r"^[0-9]+\.[0-9]+", v))


# ── SBOM loading ──────────────────────────────────────────────────────────────

def load_pkg_map(sbom_path: str) -> dict[str, dict]:
    """
    Build {name -> {ver, spdxid}} from an SPDX 2.3 JSON file.

    For packages with multiple entries (e.g. linux kernel in BST SBOMs), prefer:
      1. Semver over short-SHA
      2. Any version over None
    """
    with open(sbom_path, encoding="utf-8") as f:
        sbom = json.load(f)

    multi: dict[str, list[dict]] = {}

    for p in sbom.get("packages", []):
        name: str = p.get("name", "")
        raw:  str = p.get("versionInfo", "")
        spdxid: str = p.get("SPDXID", "")
        if not name:
            continue
        entry = {"ver": best_version(raw), "raw": raw, "spdxid": spdxid}
        multi.setdefault(name, []).append(entry)

    pkgs: dict[str, dict] = {}
    for name, entries in multi.items():
        entries.sort(key=lambda e: (0 if is_semver(e["ver"]) else 1 if e["ver"] else 2))
        pkgs[name] = entries[0]

    return pkgs


def count_packages(sbom_path: str) -> int:
    with open(sbom_path, encoding="utf-8") as f:
        sbom = json.load(f)
    return len([p for p in sbom.get("packages", []) if p.get("name")])


# ── Notable extraction ────────────────────────────────────────────────────────

def extract_notable(
    curr_map: dict,
    prev_map: dict | None,
    notable_spec: list[dict],
) -> list[dict]:
    result = []
    for spec in notable_spec:
        sbom_name    = spec["sbom_name"]
        label        = spec.get("label", sbom_name)
        spdxid_filter = spec.get("spdxid_filter")

        if sbom_name not in curr_map:
            continue

        entry = curr_map[sbom_name]
        # Optional SPDXID substring filter for disambiguation (e.g. kernel in BST SBOMs)
        if spdxid_filter and spdxid_filter not in entry.get("spdxid", ""):
            # Try to find a matching entry by walking the raw map again
            # (we collapsed to one entry per name above; skip if filter doesn't match)
            continue

        ver = entry["ver"]
        prev_ver: str | None = None
        if prev_map and sbom_name in prev_map:
            pv = prev_map[sbom_name]["ver"]
            if pv != ver:
                prev_ver = pv

        result.append({
            "name":    label,
            "version": ver or "(unknown)",
            "prev":    prev_ver,
            "changed": prev_ver is not None,
        })
    return result


# ── Full diff ─────────────────────────────────────────────────────────────────

def diff_sboms(curr_map: dict, prev_map: dict) -> dict:
    all_names = set(curr_map) | set(prev_map)
    added: list[dict] = []
    changed: list[dict] = []
    removed: list[dict] = []

    for name in sorted(all_names):
        c = curr_map.get(name)
        p = prev_map.get(name)
        cv = c["ver"] if c else None
        pv = p["ver"] if p else None

        if c and not p:
            added.append({"name": name, "version": cv or "(unknown)"})
        elif not c and p:
            removed.append({"name": name, "version": pv or "(unknown)"})
        elif cv and pv and cv != pv:
            changed.append({"name": name, "prev": pv, "curr": cv})

    return {
        "changed_count": len(changed),
        "added_count":   len(added),
        "removed_count": len(removed),
        "changed": changed,
        "added":   added,
        "removed": removed,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current",          required=True)
    ap.add_argument("--previous",         default=None)
    ap.add_argument("--notable-packages", required=True,
                    help="Path to JSON file listing notable packages")
    ap.add_argument("--output",           required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.current):
        print(f"ERROR: current SBOM not found: {args.current}", file=sys.stderr)
        sys.exit(1)

    with open(args.notable_packages, encoding="utf-8") as f:
        notable_spec: list[dict] = json.load(f)

    print(f"Loading current SBOM: {args.current}")
    curr_map = load_pkg_map(args.current)
    total    = count_packages(args.current)
    print(f"  {total} packages")

    prev_map: dict | None = None
    has_prev = False
    if args.previous and os.path.isfile(args.previous):
        print(f"Loading previous SBOM: {args.previous}")
        prev_map = load_pkg_map(args.previous)
        print(f"  {len(prev_map)} packages")
        has_prev = True

    notable   = extract_notable(curr_map, prev_map, notable_spec)
    diff_data = diff_sboms(curr_map, prev_map) if prev_map else {
        "changed_count": 0, "added_count": 0, "removed_count": 0,
        "changed": [], "added": [], "removed": [],
    }

    if has_prev:
        print(
            f"Diff: {diff_data['changed_count']} changed, "
            f"{diff_data['added_count']} added, "
            f"{diff_data['removed_count']} removed"
        )

    output = {
        "notable":        notable,
        "diff":           diff_data,
        "has_prev":       has_prev,
        "total_packages": total,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Written: {args.output}")


if __name__ == "__main__":
    main()
