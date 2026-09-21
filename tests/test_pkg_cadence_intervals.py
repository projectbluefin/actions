"""Executed coverage for the inline interval classifier in reusable-pkg-cadence.yml.

The ``Update churn counts and derive intervals`` step of
``.github/workflows/reusable-pkg-cadence.yml`` embeds a ~90-line Python program as
a heredoc. It is the sole producer of ``files/pkg-intervals.tsv``, which
``bootc-build/apply-pkg-intervals`` turns into ``user.update-interval`` xattrs and
chunkah turns into OCI layer groupings. A silent regression there mis-groups every
layer in every consumer image, and nothing else in the repository executes it.

These tests extract that heredoc from the workflow and run it against fixture
inputs, covering:

* the bootstrap heuristics used before four weeks of churn data exist,
* ``derive_interval`` thresholds once data is old enough (or ``force_reclassify``),
* rolling-window reset and eviction of packages that left the image,
* change detection against the previous version snapshot,
* the shape of the three files written back into the consumer checkout.

The extraction helper also pins the contract the tests depend on (step name,
heredoc delimiter, hardcoded RPM query path) so a rename fails loudly here rather
than silently skipping coverage.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "reusable-pkg-cadence.yml"

STEP_NAME = "Update churn counts and derive intervals"
HEREDOC_OPEN = "python3 - <<'EOF'"
CURRENT_PKGS_PATH = "/tmp/current-pkgs.tsv"
DEFAULT_INTERVALS_FILE = "files/pkg-intervals.tsv"

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _workflow() -> dict:
    assert WORKFLOW_PATH.is_file(), f"Workflow not found: {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _step_run(step_name: str) -> str:
    """Return the ``run:`` body of a named step in the update-cadence job."""
    jobs = _workflow()["jobs"]
    steps = jobs["update-cadence"]["steps"]
    for step in steps:
        if step.get("name") == step_name:
            return step["run"]
    pytest.fail(f"No step named {step_name!r} in reusable-pkg-cadence.yml")


def extract_classifier_source() -> str:
    """Extract the heredoc Python program from the interval-derivation step."""
    run_body = _step_run(STEP_NAME)
    assert HEREDOC_OPEN in run_body, (
        f"Step {STEP_NAME!r} no longer opens a {HEREDOC_OPEN!r} heredoc; "
        "update this test to match the new invocation."
    )
    after_open = run_body.split(HEREDOC_OPEN, 1)[1]
    body, delimiter, _ = after_open.partition("\nEOF")
    assert delimiter, "Heredoc opened but never terminated by a lone EOF line"
    return textwrap.dedent(body).lstrip("\n")


def run_classifier(
    tmp_path: Path,
    current_pkgs: dict[str, str],
    *,
    versions: dict | None = None,
    churn: dict | None = None,
    intervals_file: str = DEFAULT_INTERVALS_FILE,
    force_reclassify: str = "false",
) -> subprocess.CompletedProcess:
    """Run the extracted classifier in an isolated consumer checkout."""
    source = extract_classifier_source()

    current_file = tmp_path / "current-pkgs.tsv"
    current_file.write_text(
        "".join(f"{name}\t{ver}\n" for name, ver in sorted(current_pkgs.items())),
        encoding="utf-8",
    )
    # The step reads a fixed path written by the preceding `rpm -qa` step. Redirect
    # it at a per-test file so tests stay hermetic and parallel-safe; the assertion
    # keeps the redirect honest if the workflow ever changes that path.
    assert CURRENT_PKGS_PATH in source, (
        f"Classifier no longer reads {CURRENT_PKGS_PATH!r}; update the redirect."
    )
    source = source.replace(CURRENT_PKGS_PATH, str(current_file))

    consumer_files = tmp_path / "consumer" / "files"
    consumer_files.mkdir(parents=True)
    if versions is not None:
        (consumer_files / "pkg-versions.json").write_text(
            json.dumps(versions), encoding="utf-8"
        )
    if churn is not None:
        (consumer_files / "pkg-churn.json").write_text(
            json.dumps(churn), encoding="utf-8"
        )

    script = tmp_path / "classifier.py"
    script.write_text(source, encoding="utf-8")

    env = {
        **os.environ,
        "INTERVALS_FILE": intervals_file,
        "FORCE_RECLASSIFY": force_reclassify,
    }
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Classifier failed:\n{result.stderr}"
    return result


def read_intervals(tmp_path: Path, intervals_file: str = DEFAULT_INTERVALS_FILE) -> dict[str, str]:
    text = (tmp_path / "consumer" / intervals_file).read_text(encoding="utf-8")
    entries = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        name, interval = line.split("\t")
        entries[name] = interval
    return entries


def read_churn(tmp_path: Path) -> dict:
    return json.loads(
        (tmp_path / "consumer" / "files" / "pkg-churn.json").read_text(encoding="utf-8")
    )


def read_versions(tmp_path: Path) -> dict:
    return json.loads(
        (tmp_path / "consumer" / "files" / "pkg-versions.json").read_text(encoding="utf-8")
    )


def days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def churn_entry(changes: int, window_start: str, interval: str = "monthly") -> dict:
    return {"changes": changes, "window_start": window_start, "interval": interval}


class TestExtraction:
    """The heredoc contract these tests execute against."""

    def test_step_is_present_and_uses_a_quoted_heredoc(self):
        run_body = _step_run(STEP_NAME)
        assert HEREDOC_OPEN in run_body

    def test_step_receives_the_workflow_inputs_it_reads(self):
        jobs = _workflow()["jobs"]
        step = next(
            s for s in jobs["update-cadence"]["steps"] if s.get("name") == STEP_NAME
        )
        env = step.get("env", {})
        assert "INTERVALS_FILE" in env, "Classifier reads INTERVALS_FILE from the environment"
        assert "FORCE_RECLASSIFY" in env, "Classifier reads FORCE_RECLASSIFY from the environment"

    def test_extracted_source_compiles(self):
        compile(extract_classifier_source(), "pkg-cadence-classifier", "exec")


class TestBootstrapHeuristics:
    """The name-based bootstrap heuristics are currently unreachable.

    ``bootstrap_interval`` is only consulted via
    ``entry.get('interval') or bootstrap_interval(name)``, but every entry reaches
    that line through ``churn.setdefault(name, {..., 'interval': 'monthly'})``, so
    ``entry.get('interval')`` is always the truthy string ``monthly`` and the
    right-hand side never evaluates. The WEEKLY/QUARTERLY/YEARLY patterns and the
    function itself are therefore dead code, and a first run classifies every
    package as ``monthly``.

    These tests pin the behaviour that actually ships so the difference between it
    and the workflow's documented intent stays visible instead of being assumed
    away. Tracked as a defect in projectbluefin/actions#562; when that fix lands,
    ``test_first_run_classifies_every_package_as_monthly`` must be replaced with
    the per-pattern expectations it currently contradicts.
    """

    @pytest.mark.parametrize(
        "package",
        [
            "tailscale",              # WEEKLY_PAT would say weekly
            "bootc",                  # WEEKLY_PAT would say weekly
            "distrobox",              # WEEKLY_PAT would say weekly
            "ublue-update",           # WEEKLY_PAT would say weekly
            "google-noto-sans-fonts",  # YEARLY_PAT would say yearly
            "liberation-mono-fonts",   # YEARLY_PAT would say yearly
            "dejavu-sans-fonts",       # YEARLY_PAT would say yearly
            "jetbrains-mono-fonts",    # YEARLY_PAT would say yearly
            "linux-firmware",          # QUARTERLY_PAT would say quarterly
            "iwlwifi-dvm-firmware",    # QUARTERLY_PAT would say quarterly
            "atheros-firmware",        # QUARTERLY_PAT would say quarterly
            "alsa-firmware",           # QUARTERLY_PAT would say quarterly
            "bash",                    # no pattern matches: monthly either way
            "systemd",                 # no pattern matches: monthly either way
        ],
    )
    def test_first_run_classifies_every_package_as_monthly(self, tmp_path, package):
        run_classifier(tmp_path, {package: "1.0-1"})
        assert read_intervals(tmp_path)[package] == "monthly"

    def test_first_run_reports_no_reclassifications(self, tmp_path):
        result = run_classifier(tmp_path, {"tailscale": "1.0-1", "bash": "5.2-1"})
        assert "Interval reclassifications: 0" in result.stdout

    def test_bootstrap_heuristics_exist_but_are_never_consulted(self, tmp_path):
        source = extract_classifier_source()
        assert "def bootstrap_interval(name):" in source
        assert "entry.get('interval') or bootstrap_interval(name)" in source
        # The only producer of a missing 'interval' key would be a churn entry that
        # predates the setdefault default; the setdefault runs for every package in
        # the image before classification, so no such entry survives to this line.
        assert "'interval': 'monthly'" in source

    def test_explicitly_empty_recorded_interval_falls_back_to_the_heuristic(self, tmp_path):
        # The single input shape that still reaches bootstrap_interval: a churn file
        # carrying an explicitly falsy interval for a package still in the image.
        run_classifier(
            tmp_path,
            {"tailscale": "1.0-1", "google-noto-sans-fonts": "1.0-1", "linux-firmware": "1.0-1"},
            churn={
                "tailscale": {"changes": 0, "window_start": days_ago(3), "interval": ""},
                "google-noto-sans-fonts": {"changes": 0, "window_start": days_ago(3), "interval": ""},
                "linux-firmware": {"changes": 0, "window_start": days_ago(3), "interval": ""},
            },
        )
        intervals = read_intervals(tmp_path)
        assert intervals["tailscale"] == "weekly"
        assert intervals["google-noto-sans-fonts"] == "yearly"
        assert intervals["linux-firmware"] == "quarterly"

    def test_font_heuristic_is_checked_before_the_firmware_heuristic(self, tmp_path):
        run_classifier(
            tmp_path,
            {"linux-firmware-fonts": "1.0-1"},
            churn={"linux-firmware-fonts": {"changes": 0, "window_start": days_ago(3), "interval": ""}},
        )
        assert read_intervals(tmp_path)["linux-firmware-fonts"] == "yearly"

    def test_existing_interval_is_preserved_before_the_data_window_opens(self, tmp_path):
        run_classifier(
            tmp_path,
            {"bash": "5.2-1"},
            churn={"bash": churn_entry(9, days_ago(7), interval="quarterly")},
        )
        # Only one week of data: the recorded interval stands, despite 9 changes.
        assert read_intervals(tmp_path)["bash"] == "quarterly"


class TestDerivedIntervals:
    """Once four weeks of data exist, observed churn decides the interval."""

    @pytest.mark.parametrize(
        ("changes", "expected"),
        [(0, "yearly"), (1, "quarterly"), (2, "monthly"), (7, "monthly"), (8, "weekly"), (20, "weekly")],
    )
    def test_derive_interval_thresholds(self, tmp_path, changes, expected):
        run_classifier(
            tmp_path,
            {"bash": "5.2-1"},
            versions={"bash": {"version": "5.2-1", "last_seen": days_ago(28)}},
            churn={"bash": churn_entry(changes, days_ago(28))},
        )
        assert read_intervals(tmp_path)["bash"] == expected

    def test_force_reclassify_overrides_the_four_week_wait(self, tmp_path):
        run_classifier(
            tmp_path,
            {"tailscale": "1.0-1"},
            versions={"tailscale": {"version": "1.0-1", "last_seen": days_ago(3)}},
            churn={"tailscale": churn_entry(0, days_ago(3), interval="weekly")},
            force_reclassify="true",
        )
        # No observed churn, so the weekly bootstrap guess is demoted to yearly.
        assert read_intervals(tmp_path)["tailscale"] == "yearly"

    def test_reclassification_is_reported_on_stdout(self, tmp_path):
        result = run_classifier(
            tmp_path,
            {"bash": "5.2-1"},
            versions={"bash": {"version": "5.2-1", "last_seen": days_ago(30)}},
            churn={"bash": churn_entry(10, days_ago(30), interval="yearly")},
        )
        assert "bash: yearly → weekly" in result.stdout
        assert "Interval reclassifications: 1" in result.stdout


class TestChurnAccounting:
    """The rolling 90-day window is the classifier's only memory."""

    def test_version_change_increments_the_change_count(self, tmp_path):
        run_classifier(
            tmp_path,
            {"bash": "5.3-1"},
            versions={"bash": {"version": "5.2-1", "last_seen": days_ago(7)}},
            churn={"bash": churn_entry(2, days_ago(7))},
        )
        assert read_churn(tmp_path)["bash"]["changes"] == 3

    def test_unchanged_version_does_not_increment(self, tmp_path):
        run_classifier(
            tmp_path,
            {"bash": "5.2-1"},
            versions={"bash": {"version": "5.2-1", "last_seen": days_ago(7)}},
            churn={"bash": churn_entry(2, days_ago(7))},
        )
        assert read_churn(tmp_path)["bash"]["changes"] == 2

    def test_first_sighting_is_not_counted_as_churn(self, tmp_path):
        result = run_classifier(tmp_path, {"bash": "5.2-1", "systemd": "257-1"})
        assert "Changed since last snapshot: 0 packages" in result.stdout
        assert read_churn(tmp_path)["bash"]["changes"] == 0

    def test_window_older_than_ninety_days_resets_the_count(self, tmp_path):
        run_classifier(
            tmp_path,
            {"bash": "5.2-1"},
            versions={"bash": {"version": "5.2-1", "last_seen": days_ago(120)}},
            churn={"bash": churn_entry(11, days_ago(120), interval="weekly")},
        )
        entry = read_churn(tmp_path)["bash"]
        assert entry["changes"] == 0
        assert entry["window_start"] == TODAY
        # Window just reset, so there is no longer four weeks of data: interval holds.
        assert read_intervals(tmp_path)["bash"] == "weekly"

    def test_package_dropped_from_the_image_is_evicted_from_churn(self, tmp_path):
        run_classifier(
            tmp_path,
            {"bash": "5.2-1"},
            versions={"removed-pkg": {"version": "1.0-1", "last_seen": days_ago(7)}},
            churn={
                "bash": churn_entry(1, days_ago(7)),
                "removed-pkg": churn_entry(5, days_ago(7)),
            },
        )
        churn = read_churn(tmp_path)
        assert "removed-pkg" not in churn
        assert "removed-pkg" not in read_intervals(tmp_path)

    def test_churn_file_is_written_sorted(self, tmp_path):
        run_classifier(tmp_path, {"zsh": "5.9-1", "bash": "5.2-1", "fish": "3.7-1"})
        assert list(read_churn(tmp_path)) == ["bash", "fish", "zsh"]


class TestWrittenFiles:
    """The three files handed back to the consumer repo."""

    def test_versions_snapshot_records_version_and_last_seen(self, tmp_path):
        run_classifier(tmp_path, {"bash": "5.2-1"})
        assert read_versions(tmp_path) == {"bash": {"version": "5.2-1", "last_seen": TODAY}}

    def test_intervals_file_carries_a_do_not_edit_header(self, tmp_path):
        run_classifier(tmp_path, {"bash": "5.2-1"})
        text = (tmp_path / "consumer" / DEFAULT_INTERVALS_FILE).read_text(encoding="utf-8")
        first_line = text.splitlines()[0]
        assert first_line.startswith("#")
        assert "do not edit by hand" in first_line
        assert text.endswith("\n")

    def test_intervals_entries_are_sorted_by_package_name(self, tmp_path):
        run_classifier(tmp_path, {"zsh": "5.9-1", "bash": "5.2-1", "fish": "3.7-1"})
        assert list(read_intervals(tmp_path)) == ["bash", "fish", "zsh"]

    def test_entry_count_is_reported_on_stdout(self, tmp_path):
        result = run_classifier(tmp_path, {"bash": "5.2-1", "zsh": "5.9-1"})
        assert "Written 2 entries to" in result.stdout

    def test_custom_intervals_path_is_honoured_and_parents_created(self, tmp_path):
        run_classifier(
            tmp_path,
            {"bash": "5.2-1"},
            intervals_file="build/cadence/intervals.tsv",
        )
        assert read_intervals(tmp_path, "build/cadence/intervals.tsv") == {"bash": "monthly"}

    def test_malformed_rpm_query_lines_are_skipped(self, tmp_path):
        current_file = tmp_path / "current-pkgs.tsv"
        source = extract_classifier_source().replace(CURRENT_PKGS_PATH, str(current_file))
        (tmp_path / "consumer" / "files").mkdir(parents=True)
        current_file.write_text("bash\t5.2-1\ngarbage-without-a-tab\n", encoding="utf-8")
        script = tmp_path / "classifier.py"
        script.write_text(source, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            env={**os.environ, "INTERVALS_FILE": DEFAULT_INTERVALS_FILE},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert read_intervals(tmp_path) == {"bash": "monthly"}
