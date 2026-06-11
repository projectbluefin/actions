"""
Tests for scripts/monitor_pipeline.py — factory health computation core.

Covers: time-window filtering, success rate calculation, threshold boundary,
alert vs healthy status, issue deduplication, markdown failure links,
no-runs edge case, and aggregate_health summary.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

# The script under test — conftest.py already patches sys.path
from monitor_pipeline import (
    compute_pipeline_health,
    should_open_issue,
    aggregate_health,
    _parse_epoch,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _epoch_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _make_run(
    conclusion: str = "success",
    status: str = "completed",
    minutes_ago: int = 60,
    url: str = "https://github.com/org/repo/actions/runs/1",
) -> dict:
    """Build a minimal run dict for testing."""
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "createdAt": ts,
        "status": status,
        "conclusion": conclusion,
        "url": url,
    }


CUTOFF_1H_AGO = (_epoch_now() - 3600)   # 1 hour ago as cutoff
CUTOFF_1D_AGO = (_epoch_now() - 86400)  # 24 hours ago as cutoff


# ── _parse_epoch ──────────────────────────────────────────────────────────────

class TestParseEpoch:
    def test_parses_z_suffix(self):
        ts = "2026-06-01T12:00:00Z"
        epoch = _parse_epoch(ts)
        assert epoch > 0
        # Should be approx 2026-06-01 12:00 UTC
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        assert dt.year == 2026
        assert dt.month == 6

    def test_parses_plus_offset(self):
        ts = "2026-06-01T12:00:00+00:00"
        epoch = _parse_epoch(ts)
        assert epoch > 0

    def test_empty_string_returns_zero(self):
        assert _parse_epoch("") == 0.0

    def test_invalid_string_returns_zero(self):
        assert _parse_epoch("not-a-date") == 0.0


# ── compute_pipeline_health ───────────────────────────────────────────────────

class TestComputePipelineHealth:
    def test_all_success_runs_are_healthy(self):
        runs = [_make_run("success", minutes_ago=30) for _ in range(5)]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["total"] == 5
        assert result["success"] == 5
        assert result["rate_value"] == 100
        assert result["status"] == "healthy"

    def test_all_failed_runs_are_alert(self):
        runs = [_make_run("failure", minutes_ago=30) for _ in range(4)]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["status"] == "alert"
        assert result["rate_value"] == 0
        assert result["rate_display"] == "0%"

    def test_no_runs_returns_no_runs_status(self):
        result = compute_pipeline_health([], CUTOFF_1H_AGO)
        assert result["total"] == 0
        assert result["rate_value"] == -1
        assert result["rate_display"] == "n/a"
        assert result["status"] == "no-runs"

    def test_runs_outside_window_excluded(self):
        # One run inside the window, one outside
        inside = _make_run("success", minutes_ago=30)
        outside = _make_run("failure", minutes_ago=120)  # 2h ago, outside 1h window
        result = compute_pipeline_health([inside, outside], CUTOFF_1H_AGO)
        assert result["total"] == 1
        assert result["success"] == 1

    def test_threshold_boundary_exactly_at_threshold_is_healthy(self):
        # 4 success, 1 failure = 80% — exactly at threshold → healthy
        runs = [_make_run("success", minutes_ago=30) for _ in range(4)]
        runs.append(_make_run("failure", minutes_ago=30))
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["rate_value"] == 80
        assert result["status"] == "healthy"

    def test_threshold_boundary_one_below_is_alert(self):
        # 3 success, 1 failure = 75% — below 80% threshold → alert
        runs = [_make_run("success", minutes_ago=30) for _ in range(3)]
        runs.append(_make_run("failure", minutes_ago=30))
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["rate_value"] == 75
        assert result["status"] == "alert"

    def test_skipped_runs_excluded_from_total(self):
        success = _make_run("success", minutes_ago=30)
        skipped = _make_run("skipped", minutes_ago=30)
        result = compute_pipeline_health([success, skipped], CUTOFF_1H_AGO)
        assert result["total"] == 1  # skipped doesn't count
        assert result["success"] == 1

    def test_in_progress_runs_excluded(self):
        success = _make_run("success", minutes_ago=30)
        in_progress = _make_run(conclusion="", status="in_progress", minutes_ago=10)
        result = compute_pipeline_health([success, in_progress], CUTOFF_1H_AGO)
        assert result["total"] == 1

    def test_failures_md_contains_up_to_5_links(self):
        runs = [
            _make_run("failure", minutes_ago=30, url=f"https://github.com/runs/{i}")
            for i in range(7)
        ]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO)
        lines = [l for l in result["failures_md"].split("\n") if l.strip()]
        assert len(lines) == 5  # capped at 5

    def test_failures_md_format_matches_markdown_link(self):
        runs = [_make_run("failure", minutes_ago=30, url="https://github.com/runs/42")]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO)
        assert "- [failure](https://github.com/runs/42)" in result["failures_md"]

    def test_all_runs_outside_window_returns_no_runs(self):
        runs = [_make_run("success", minutes_ago=3000)]  # 50h ago
        # 24h cutoff
        result = compute_pipeline_health(runs, CUTOFF_1D_AGO)
        assert result["status"] == "no-runs"

    def test_mixed_conclusions_rate_calculation(self):
        # 6 success, 2 failure, 2 cancelled = 10 total, 60% success
        runs = (
            [_make_run("success", minutes_ago=30) for _ in range(6)]
            + [_make_run("failure", minutes_ago=30) for _ in range(2)]
            + [_make_run("cancelled", minutes_ago=30) for _ in range(2)]
        )
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["total"] == 10
        assert result["success"] == 6
        assert result["rate_value"] == 60
        assert result["status"] == "alert"


# ── should_open_issue ─────────────────────────────────────────────────────────

class TestShouldOpenIssue:
    def _alert_health(self) -> dict:
        return {"rate_value": 50, "status": "alert"}

    def _healthy_health(self) -> dict:
        return {"rate_value": 90, "status": "healthy"}

    def test_opens_issue_when_alert_and_no_duplicate(self):
        assert should_open_issue(self._alert_health(), [], "fix(factory): [org/repo]")

    def test_suppresses_issue_when_healthy(self):
        assert not should_open_issue(self._healthy_health(), [], "fix(factory): [org/repo]")

    def test_suppresses_issue_when_no_runs(self):
        no_runs = {"rate_value": -1, "status": "no-runs"}
        assert not should_open_issue(no_runs, [], "fix(factory): [org/repo]")

    def test_suppresses_duplicate_when_open_issue_exists(self):
        existing = [{"title": "fix(factory): [org/repo] rate dropped to 50% (24h window)"}]
        assert not should_open_issue(self._alert_health(), existing, "fix(factory): [org/repo]")

    def test_opens_issue_when_existing_issue_has_different_prefix(self):
        existing = [{"title": "fix(factory): [other/repo] something else"}]
        assert should_open_issue(self._alert_health(), existing, "fix(factory): [org/repo]")


# ── aggregate_health ──────────────────────────────────────────────────────────

class TestAggregateHealth:
    def test_all_healthy(self):
        results = [{"status": "healthy"} for _ in range(5)]
        agg = aggregate_health(results)
        assert agg["healthy_count"] == 5
        assert agg["alert_count"] == 0
        assert agg["no_runs_count"] == 0

    def test_mixed_statuses(self):
        results = [
            {"status": "healthy"},
            {"status": "alert"},
            {"status": "alert"},
            {"status": "no-runs"},
        ]
        agg = aggregate_health(results)
        assert agg["total_pipelines"] == 4
        assert agg["healthy_count"] == 1
        assert agg["alert_count"] == 2
        assert agg["no_runs_count"] == 1

    def test_empty_results(self):
        agg = aggregate_health([])
        assert agg["total_pipelines"] == 0
        assert agg["alert_count"] == 0
