"""
Tests for the alert-routing contract in `.github/workflows/factory-health.yml`.

The app-token step is `continue-on-error: true` so a token failure cannot stop
the health checks. The cost is that the job still concludes `success` while
alerts are filed in the wrong repository — projectbluefin/actions#556, where
that fallback ran unnoticed for months because the checks UI stayed green.

These tests pin both halves of the fix:

  - the monitor step reports which destination it actually used, and stamps a
    misroute banner onto any alert it has to file in the fallback repo;
  - a later step turns the `fallback` state into a non-zero exit, so a
    misrouted run is never green again.

The routing preamble is executed as real bash rather than pattern-matched, so
the assertions cover behaviour and not wording.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "factory-health.yml"

# First line of the monitoring logic proper; everything above it is the routing
# decision under test.
PREAMBLE_END = "monitor_pipeline() {"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def job() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["monitor"]


@pytest.fixture(scope="module")
def steps(job: dict) -> list[dict]:
    return job["steps"]


def _step_with_id(steps: list[dict], step_id: str) -> dict:
    for step in steps:
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"no step with id {step_id!r} in factory-health.yml")


@pytest.fixture(scope="module")
def routing_preamble(steps: list[dict]) -> str:
    """The monitor step's script, truncated just before the monitoring logic."""
    script = _step_with_id(steps, "monitor")["run"]
    head, sep, _ = script.partition(PREAMBLE_END)
    assert sep, f"{PREAMBLE_END!r} not found — the preamble slice needs updating"
    return head


def _run_preamble(preamble: str, tmp_path: Path, token: str) -> dict:
    """Execute the routing preamble with a given app token and report its state."""
    outputs = tmp_path / "github_output"
    outputs.touch()
    banner = tmp_path / "banner"
    author = tmp_path / "author"

    script = (
        f'{preamble}\nprintf "%s" "${{misroute_banner}}" > "{banner}"\n'
        f'printf "%s" "${{ISSUE_AUTHOR}}" > "{author}"\n'
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "COMMON_ISSUE_TOKEN": token,
            "APP_TOKEN_OUTCOME": "success" if token else "failure",
            "APP_SLUG": "mergeraptor" if token else "",
            "GH_TOKEN": "ghs_workflow_token",
            "GITHUB_REPOSITORY": "projectbluefin/actions",
            "GITHUB_OUTPUT": str(outputs),
        },
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"preamble failed: {proc.stderr}"

    parsed = dict(
        line.split("=", 1)
        for line in outputs.read_text().splitlines()
        if "=" in line
    )
    return {
        "outputs": parsed,
        "banner": banner.read_text(),
        "author": author.read_text(),
        "stdout": proc.stdout,
    }


# ── Routing decision ──────────────────────────────────────────────────────────

class TestRoutingDecision:
    def test_token_available_routes_to_common(self, routing_preamble, tmp_path):
        result = _run_preamble(routing_preamble, tmp_path, token="ghs_app_token")
        assert result["outputs"]["alert_routing"] == "intended"
        assert result["outputs"]["intended_issue_repo"] == "projectbluefin/common"

    def test_token_available_emits_no_warning(self, routing_preamble, tmp_path):
        result = _run_preamble(routing_preamble, tmp_path, token="ghs_app_token")
        assert "::warning::" not in result["stdout"]

    def test_token_available_leaves_banner_empty(self, routing_preamble, tmp_path):
        result = _run_preamble(routing_preamble, tmp_path, token="ghs_app_token")
        assert result["banner"] == ""

    def test_missing_token_reports_fallback(self, routing_preamble, tmp_path):
        result = _run_preamble(routing_preamble, tmp_path, token="")
        assert result["outputs"]["alert_routing"] == "fallback"

    def test_missing_token_records_both_repos(self, routing_preamble, tmp_path):
        result = _run_preamble(routing_preamble, tmp_path, token="")
        assert result["outputs"]["intended_issue_repo"] == "projectbluefin/common"
        assert result["outputs"]["fallback_issue_repo"] == "projectbluefin/actions"

    def test_missing_token_warns_with_app_token_outcome(self, routing_preamble, tmp_path):
        # The old message said only "the token is unavailable", which left the
        # reader digging through raw logs for the API error.
        result = _run_preamble(routing_preamble, tmp_path, token="")
        assert "::warning::" in result["stdout"]
        assert "app-token step: failure" in result["stdout"]

    def test_missing_token_stamps_misroute_banner(self, routing_preamble, tmp_path):
        result = _run_preamble(routing_preamble, tmp_path, token="")
        banner = result["banner"]
        assert "[!WARNING]" in banner
        assert "misrouted" in banner
        assert "projectbluefin/common" in banner

    def test_close_pass_author_is_the_app_bot(self, routing_preamble, tmp_path):
        # The close pass only touches issues this login opened; if it does not
        # match what `gh issue list` reports, no alert ever closes again.
        result = _run_preamble(routing_preamble, tmp_path, token="ghs_app_token")
        assert result["author"] == "app/mergeraptor"

    def test_fallback_close_pass_author_is_the_workflow_bot(self, routing_preamble, tmp_path):
        result = _run_preamble(routing_preamble, tmp_path, token="")
        assert result["author"] == "app/github-actions"


# ── Dedupe contract ───────────────────────────────────────────────────────────

class TestDedupeContract:
    def test_monitor_step_declares_app_slug(self, steps):
        monitor_step = _step_with_id(steps, "monitor")
        assert "APP_SLUG" in monitor_step.get("env", {})
        assert monitor_step["env"]["APP_SLUG"] == "${{ steps.app-token.outputs.app-slug }}"

    def test_issue_list_fetches_author(self, steps):
        script = _step_with_id(steps, "monitor")["run"]
        joined = script.replace("\\\n", " ")
        match = re.search(r"open_issues_json=\$\(.*?\bgh issue list\b.*?--json\s+([a-zA-Z0-9_,]+)", joined)
        assert match, "no `open_issues_json=$(... gh issue list ... --json ...)` found in monitor step"
        fields = [f.strip() for f in match.group(1).split(",")]
        assert "author" in fields

    def test_dedupe_filters_by_author(self, steps):
        script = _step_with_id(steps, "monitor")["run"]
        assert "select(.author.login == $author)" in script

# ── Visibility contract ───────────────────────────────────────────────────────

class TestVisibilityContract:
    def test_app_token_step_stays_best_effort(self, steps):
        # Health checks must survive a token failure; that is what makes the
        # verification step below necessary rather than redundant.
        assert _step_with_id(steps, "app-token")["continue-on-error"] is True

    def test_a_step_fails_the_job_on_fallback_routing(self, steps):
        failing = [
            step
            for step in steps
            if "alert_routing == 'fallback'" in str(step.get("if", ""))
            and "exit 1" in step.get("run", "")
        ]
        assert failing, (
            "no step fails the run when alerts are misrouted — a degraded run "
            "would conclude `success` again (projectbluefin/actions#556)"
        )

    def test_verification_runs_after_the_monitor_step(self, steps):
        # The health summary must be produced before the job goes red, so a
        # misrouted run is still a useful one.
        ids = [step.get("id") or step.get("name") for step in steps]
        assert ids.index("monitor") < ids.index("Verify alert routing")

    def test_verification_still_runs_when_monitoring_fails(self, steps):
        assert "always()" in _step_with_id_by_name(steps, "Verify alert routing")["if"]


def _step_with_id_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in factory-health.yml")
