#!/usr/bin/env python3
"""
render_gate_section.py — Replace the gate checklist section in a promotion PR body.

The promote job writes the PR body with <!-- gate-section-start/end --> markers
and ⏳ placeholders.  After gate checks complete, the gate job calls this script
with the actual results to produce an updated body file via gh pr edit --body-file.

Usage:
    python3 render_gate_section.py \\
        --body-file      /tmp/current-pr-body.md \\
        --output         /tmp/updated-pr-body.md \\
        --resolve-ok     true \\
        --resolve-summary "2 variants resolved." \\
        --verify-ok      true \\
        --verify-summary "All signatures verified via Sigstore." \\
        --e2e-state      passed \\
        --e2e-summary    "Smoke suite passed." \\
        --e2e-details    "https://github.com/.../runs/99" \\
        --ready          true
"""
import argparse
import re
import sys

GATE_START = "<!-- gate-section-start -->"
GATE_END   = "<!-- gate-section-end -->"

_STATE_ICON: dict[str, str] = {
    "passed":  "✅",
    "failed":  "❌",
    "skipped": "⏭️",
    "waiting": "⏳",
    "stale":   "⚠️",
    "error":   "❌",
}


# ── Core functions ─────────────────────────────────────────────────────────────

def _icon(ok_str: str, state: str = "") -> str:
    if state in _STATE_ICON:
        return _STATE_ICON[state]
    return "✅" if ok_str == "true" else "❌"


def build_gate_section(
    *,
    resolve_ok: str,
    resolve_summary: str,
    verify_ok: str,
    verify_summary: str,
    e2e_state: str,
    e2e_summary: str,
    e2e_details: str,
    ready: str,
) -> str:
    e2e_icon = _icon("", e2e_state)

    # Build e2e detail cell — link the summary to the run URL when available
    if e2e_details and e2e_details.startswith("http"):
        e2e_cell = f"[{e2e_summary}]({e2e_details})"
    elif e2e_details:
        e2e_cell = f"{e2e_summary} {e2e_details}".strip()
    else:
        e2e_cell = e2e_summary

    verify_label = "passed" if verify_ok == "true" else "failed"

    rows = "\n".join([
        f"| Digest resolution | {_icon(resolve_ok)} {'passed' if resolve_ok == 'true' else 'failed'} | {resolve_summary} |",
        f"| Cosign signatures | {_icon(verify_ok)} {verify_label} | {verify_summary} |",
        f"| E2E               | {e2e_icon} {e2e_state} | {e2e_cell} |",
    ])

    overall = "✅ All checks passed" if ready == "true" else "❌ Gate blocked"

    return (
        f"{GATE_START}\n"
        "### Release checklist\n\n"
        f"**{overall}**\n\n"
        "| Check | Status | Details |\n"
        "|---|---|---|\n"
        f"{rows}\n"
        f"{GATE_END}\n"
    )


def replace_gate_section(body: str, new_section: str) -> str:
    """Replace content between the gate section markers.

    Raises ValueError if the markers are not found in body.
    """
    if GATE_START not in body or GATE_END not in body:
        raise ValueError(
            f"PR body does not contain gate-section markers "
            f"({GATE_START!r} / {GATE_END!r}). Cannot update."
        )
    pattern = re.compile(
        re.escape(GATE_START) + r".*?" + re.escape(GATE_END),
        re.DOTALL,
    )
    return pattern.sub(new_section.rstrip("\n"), body)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Update the gate checklist section in a promotion PR body"
    )
    ap.add_argument("--body-file",       required=True,
                    help="Path to the current PR body markdown (read-only)")
    ap.add_argument("--output",          required=True,
                    help="Path to write the updated body")
    ap.add_argument("--resolve-ok",      required=True)
    ap.add_argument("--resolve-summary", required=True)
    ap.add_argument("--verify-ok",       required=True)
    ap.add_argument("--verify-summary",  required=True)
    ap.add_argument("--e2e-state",       required=True,
                    help="passed | failed | skipped | waiting | stale | error")
    ap.add_argument("--e2e-summary",     required=True)
    ap.add_argument("--e2e-details",     default="",
                    help="Run URL or extra detail for the e2e row (optional)")
    ap.add_argument("--ready",           required=True,
                    help="true if all gate checks passed, false otherwise")
    args = ap.parse_args()

    with open(args.body_file, encoding="utf-8") as f:
        current_body = f.read()

    try:
        new_section  = build_gate_section(
            resolve_ok=args.resolve_ok,
            resolve_summary=args.resolve_summary,
            verify_ok=args.verify_ok,
            verify_summary=args.verify_summary,
            e2e_state=args.e2e_state,
            e2e_summary=args.e2e_summary,
            e2e_details=args.e2e_details,
            ready=args.ready,
        )
        updated_body = replace_gate_section(current_body, new_section)
    except ValueError as exc:
        print(f"::warning::{exc}", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(updated_body)
    print(f"Gate section updated: {args.output} ({len(updated_body):,} chars)")


if __name__ == "__main__":
    main()
