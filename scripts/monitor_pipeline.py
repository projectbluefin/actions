#!/usr/bin/env python3
"""
monitor_pipeline — factory health computation core

Extracted from .github/workflows/factory-health.yml for unit testing.
Called by factory-health.yml after passing runs JSON as arguments.

Usage (from workflow):
    python3 scripts/monitor_pipeline.py \
        --runs-json "$RUNS_JSON" \
        --repo "projectbluefin/bluefin" \
        --pipeline "Build" \
        --workflow "Testing Images" \
        --threshold 80 \
        --window-hours 24 \
        --output result.json

The output JSON matches the shape written by monitor_pipeline() in the
original bash workflow:
    {
        "repo": "...", "pipeline": "...", "workflow": "...",
        "total": N, "success": N, "rate_value": N,
        "rate_display": "N%" | "n/a", "status": "healthy"|"alert"|"no-runs",
        "failures_md": "- [conclusion](url)\n..."
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


def compute_pipeline_health(
    runs: list[dict],
    cutoff_epoch: float,
    threshold: int = 80,
) -> dict:
    """
    Given a list of workflow run dicts (from ``gh run list --json``),
    filter to the recent window, compute success rate, and return a
    structured health result.

    Parameters
    ----------
    runs:
        List of run dicts.  Each must have at minimum:
        - ``createdAt``: ISO-8601 timestamp string
        - ``status``: "completed" | "in_progress" | "queued" | ...
        - ``conclusion``: "success" | "failure" | "cancelled" | "skipped" | None
        - ``url``: run URL string
    cutoff_epoch:
        Unix timestamp; runs created before this are excluded.
    threshold:
        Success-rate threshold (0–100) below which status becomes "alert".

    Returns
    -------
    dict with keys:
        total, success, rate_value, rate_display, status, failures_md
    """
    # Filter to the time window
    recent = [
        r for r in runs
        if _parse_epoch(r.get("createdAt", "")) >= cutoff_epoch
    ]

    # Only completed, non-skipped runs count
    completed = [
        r for r in recent
        if r.get("status") == "completed" and r.get("conclusion") != "skipped"
    ]

    total = len(completed)
    success_count = sum(1 for r in completed if r.get("conclusion") == "success")

    if total > 0:
        rate_value = (success_count * 100) // total
        rate_display = f"{rate_value}%"
        if rate_value < threshold:
            status = "alert"
        else:
            status = "healthy"
    else:
        rate_value = -1
        rate_display = "n/a"
        status = "no-runs"

    # Up to 5 failing run markdown links
    failures = [
        r for r in completed if r.get("conclusion") != "success"
    ][:5]
    failures_md = "\n".join(
        f"- [{r['conclusion']}]({r['url']})" for r in failures
    )

    return {
        "total": total,
        "success": success_count,
        "rate_value": rate_value,
        "rate_display": rate_display,
        "status": status,
        "failures_md": failures_md,
    }


def should_open_issue(
    health: dict,
    existing_issues: list[dict],
    title_prefix: str,
) -> bool:
    """
    Return True if a new alert issue should be opened for this pipeline.

    An issue is suppressed when:
    - The pipeline is healthy (rate_value >= threshold → status != "alert")
    - rate_value is -1 (no-runs window — no data to alert on)
    - An open issue with matching title prefix already exists
    """
    if health["rate_value"] < 0 or health["status"] != "alert":
        return False
    for issue in existing_issues:
        if issue.get("title", "").startswith(title_prefix):
            return True if False else False  # existing → don't open again
    # No duplicate found → should open
    return True


def _parse_epoch(ts: str) -> float:
    """Parse an ISO-8601 UTC timestamp to a Unix epoch float."""
    if not ts:
        return 0.0
    # Python 3.11+ handles Z suffix; for older versions strip and add +00:00
    ts_clean = ts.rstrip("Z")
    if "+" not in ts_clean and ts_clean.count("-") <= 2:
        ts_clean += "+00:00"
    try:
        return datetime.fromisoformat(ts_clean).timestamp()
    except ValueError:
        return 0.0


def aggregate_health(results: list[dict]) -> dict:
    """
    Aggregate a list of pipeline health results into a summary dict.

    Returns
    -------
    dict with keys:
        total_pipelines, healthy_count, alert_count, no_runs_count
    """
    healthy = sum(1 for r in results if r.get("status") == "healthy")
    alert = sum(1 for r in results if r.get("status") == "alert")
    no_runs = sum(1 for r in results if r.get("status") == "no-runs")
    return {
        "total_pipelines": len(results),
        "healthy_count": healthy,
        "alert_count": alert,
        "no_runs_count": no_runs,
    }


def main() -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-json", required=True, help="JSON array of run objects")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pipeline", required=True)
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--threshold", type=int, default=80)
    ap.add_argument("--window-hours", type=int, default=24)
    ap.add_argument("--output", required=True, help="Output JSON path")
    args = ap.parse_args()

    from datetime import timedelta

    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=args.window_hours)
    ).timestamp()

    with open(args.runs_json) as f:
        runs = json.load(f)

    health = compute_pipeline_health(runs, cutoff, args.threshold)
    result = {
        "repo": args.repo,
        "pipeline": args.pipeline,
        "workflow": args.workflow,
        **health,
    }

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"{args.repo} / {args.pipeline}: {health['rate_display']} ({health['status']})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
