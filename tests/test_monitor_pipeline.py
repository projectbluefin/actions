"""
Tests for scripts/monitor_pipeline.py — factory health computation core.

Covers: time-window filtering, success rate calculation, threshold boundary,
alert vs healthy status, the minimum-sample floor and its consecutive-failure
escalation, issue deduplication, markdown failure links, no-runs edge case,
and aggregate_health summary.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

# The script under test — conftest.py already patches sys.path
from monitor_pipeline import (
    compute_pipeline_health,
    should_open_issue,
    aggregate_health,
    _consecutive_failures,
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

    def test_genuine_outcomes_only_count(self):
        # 6 success, 2 failure, 2 cancelled -> cancelled excluded: 8 total, 75%
        runs = (
            [_make_run("success", minutes_ago=30) for _ in range(6)]
            + [_make_run("failure", minutes_ago=30) for _ in range(2)]
            + [_make_run("cancelled", minutes_ago=30) for _ in range(2)]
        )
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["total"] == 8
        assert result["success"] == 6
        assert result["rate_value"] == 75
        assert result["status"] == "alert"

    def test_cancelled_and_action_required_excluded(self):
        # The bug this fix addresses: cancelled (preempted) and action_required
        # (pending approval) runs must NOT count against the success rate.
        # Mirrors projectbluefin/actions#483: 6 success + 1 cancelled + 1
        # action_required reported 75% instead of 100%.
        runs = (
            [_make_run("success", minutes_ago=30) for _ in range(6)]
            + [_make_run("cancelled", minutes_ago=30)]
            + [_make_run("action_required", minutes_ago=30)]
        )
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["total"] == 6
        assert result["success"] == 6
        assert result["rate_value"] == 100
        assert result["status"] == "healthy"

    def test_failures_md_ignores_non_outcomes(self):
        # Cancelled/action_required must not appear as "failing runs".
        runs = [
            _make_run("success", minutes_ago=30),
            _make_run("cancelled", minutes_ago=30, url="https://github.com/runs/c1"),
            _make_run("action_required", minutes_ago=30, url="https://github.com/runs/a1"),
        ]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO)
        assert result["failures_md"] == ""


# ── minimum-sample floor ──────────────────────────────────────────────────────

class TestMinimumSampleFloor:
    """
    A once-a-day pipeline puts exactly one run in a 24h window, so the only
    rates it can report are 100% and 0%. Without a sample floor, one flake
    files a P0 (projectbluefin/actions#479).
    """

    def test_single_failed_run_is_low_sample_not_alert(self):
        # The #479 shape: Nightly E2E, 0/1 in the window, nothing before it.
        runs = [_make_run("failure", minutes_ago=30)]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["total"] == 1
        assert result["rate_value"] == 0
        assert result["status"] == "low-sample"

    def test_low_sample_does_not_open_an_issue(self):
        runs = [_make_run("failure", minutes_ago=30)]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert not should_open_issue(result, [], "fix(factory): [org/repo]")

    def test_sample_at_the_floor_still_alerts(self):
        # 3 completed runs (the default floor), 1 success → 33% → alert
        runs = [_make_run("failure", minutes_ago=30) for _ in range(2)]
        runs.append(_make_run("success", minutes_ago=30))
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["total"] == 3
        assert result["status"] == "alert"

    def test_floor_never_suppresses_a_healthy_pipeline(self):
        runs = [_make_run("success", minutes_ago=30)]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["status"] == "healthy"

    def test_consecutive_failures_escalate_an_under_sampled_pipeline(self):
        # One failure in the window, but the night before failed too — the
        # floor must not become a blind spot for a pipeline that is down.
        runs = [
            _make_run("failure", minutes_ago=30),
            _make_run("failure", minutes_ago=24 * 60 + 30),  # outside the window
        ]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["total"] == 1
        assert result["consecutive_failures"] == 2
        assert result["status"] == "alert"

    def test_recent_success_breaks_the_failure_streak(self):
        runs = [
            _make_run("failure", minutes_ago=30),
            _make_run("success", minutes_ago=24 * 60 + 30),
            _make_run("failure", minutes_ago=48 * 60 + 30),
        ]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, threshold=80)
        assert result["consecutive_failures"] == 1
        assert result["status"] == "low-sample"

    def test_min_runs_is_configurable(self):
        runs = [_make_run("failure", minutes_ago=30) for _ in range(4)]
        result = compute_pipeline_health(
            runs, CUTOFF_1H_AGO, threshold=80, min_runs=5,
            min_consecutive_failures=99,
        )
        assert result["status"] == "low-sample"

    def test_no_runs_still_reports_no_runs(self):
        result = compute_pipeline_health([], CUTOFF_1H_AGO, threshold=80)
        assert result["status"] == "no-runs"

    def test_min_runs_is_reported_on_the_result(self):
        runs = [_make_run("success", minutes_ago=30)]
        result = compute_pipeline_health(runs, CUTOFF_1H_AGO, min_runs=7)
        assert result["min_runs"] == 7


# ── _consecutive_failures ─────────────────────────────────────────────────────

class TestConsecutiveFailures:
    def test_empty_history_is_zero(self):
        assert _consecutive_failures([]) == 0

    def test_counts_only_the_leading_streak(self):
        runs = [
            _make_run("failure", minutes_ago=10),
            _make_run("failure", minutes_ago=20),
            _make_run("success", minutes_ago=30),
            _make_run("failure", minutes_ago=40),
        ]
        assert _consecutive_failures(runs) == 2

    def test_never_succeeded_counts_whole_history(self):
        runs = [_make_run("failure", minutes_ago=10 * i) for i in range(1, 5)]
        assert _consecutive_failures(runs) == 4

    def test_ordering_is_derived_from_timestamps_not_list_order(self):
        # Oldest-first input must yield the same answer as newest-first.
        runs = [
            _make_run("success", minutes_ago=40),
            _make_run("failure", minutes_ago=20),
            _make_run("failure", minutes_ago=10),
        ]
        assert _consecutive_failures(runs) == 2

    def test_cancelled_and_in_progress_runs_do_not_break_the_streak(self):
        runs = [
            _make_run("failure", minutes_ago=10),
            _make_run("cancelled", minutes_ago=20),
            _make_run(conclusion="", status="in_progress", minutes_ago=25),
            _make_run("failure", minutes_ago=30),
            _make_run("success", minutes_ago=40),
        ]
        assert _consecutive_failures(runs) == 2


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

    def test_suppresses_issue_when_low_sample(self):
        low_sample = {"rate_value": 0, "status": "low-sample"}
        assert not should_open_issue(low_sample, [], "fix(factory): [org/repo]")

    def test_suppresses_duplicate_when_open_issue_exists(self):
        existing = [{"title": "fix(factory): [org/repo] rate dropped to 50% (24h window)"}]
        assert not should_open_issue(self._alert_health(), existing, "fix(factory): [org/repo]")

    def test_opens_issue_when_existing_issue_has_different_prefix(self):
        existing = [{"title": "fix(factory): [other/repo] something else"}]
        assert should_open_issue(self._alert_health(), existing, "fix(factory): [org/repo]")

    def test_suppresses_duplicate_when_open_issue_matches_author(self):
        existing = [
            {
                "title": "fix(factory): [org/repo] rate dropped to 50% (24h window)",
                "author": {"login": "app/mergeraptor"},
            }
        ]
        assert not should_open_issue(
            self._alert_health(), existing, "fix(factory): [org/repo]", author="app/mergeraptor"
        )

    def test_opens_issue_when_existing_issue_has_different_author(self):
        existing = [
            {
                "title": "fix(factory): [org/repo] rate dropped to 50% (24h window)",
                "author": {"login": "human-contributor"},
            }
        ]
        assert should_open_issue(
            self._alert_health(), existing, "fix(factory): [org/repo]", author="app/mergeraptor"
        )

    def test_opens_issue_when_existing_issue_has_missing_or_empty_author(self):
        existing = [
            {"title": "fix(factory): [org/repo] rate dropped to 50% (24h window)"},
            {"title": "fix(factory): [org/repo] rate dropped to 50% (24h window)", "author": None},
            {"title": "fix(factory): [org/repo] rate dropped to 50% (24h window)", "author": {"login": ""}},
        ]
        assert should_open_issue(
            self._alert_health(), existing, "fix(factory): [org/repo]", author="app/mergeraptor"
        )


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
            {"status": "low-sample"},
        ]
        agg = aggregate_health(results)
        assert agg["total_pipelines"] == 5
        assert agg["healthy_count"] == 1
        assert agg["alert_count"] == 2
        assert agg["no_runs_count"] == 1
        assert agg["low_sample_count"] == 1

    def test_empty_results(self):
        agg = aggregate_health([])
        assert agg["total_pipelines"] == 0
        assert agg["alert_count"] == 0
