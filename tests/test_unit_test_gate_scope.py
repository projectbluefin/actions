"""Drift gate for the unit-test trigger scope.

Several tests in this suite are *drift gates over workflow files*: they read a
`.github/workflows/*.yml` and assert something about its contents — that an
inline `run:` body still matches its extracted script
(`test_release_gate_single_source.py`), that job ordering still enforces the
release gate (`test_promote_gate_order.py`), that cosign/skopeo call sites are
still declared (`test_trust_policy_single_source.py`), and so on.

Those gates are only as good as the events that run them. `unit-tests.yml`
filters on `paths:`, so a pull request that edits *only* a guarded workflow does
not run pytest at all, and the gate that exists to protect that exact file stays
silent. The guarded set and the trigger set are two separate hand-maintained
lists, and nothing kept them in agreement.

This test makes the trigger scope a derived consequence of the suite: every
workflow file the suite reads must be reachable by `unit-tests.yml`'s `paths:`
filter, on both `push` and `pull_request`. Adding a gate over a new workflow now
forces the corresponding trigger entry in the same change.
"""
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
UNIT_TESTS_WORKFLOW = WORKFLOW_DIR / "unit-tests.yml"

_YAML_TOKEN = re.compile(r"[A-Za-z0-9_.-]+\.ya?ml")

# Workflow files this gate found blind at the time it was written, and which it
# cannot itself repair: the fix is an edit to `.github/workflows/unit-tests.yml`.
# Each entry is a live gap, not an acceptance. `test_no_stale_known_blind_spots`
# fails once an entry is covered, forcing it back out of this list; growing the
# list requires an explicit edit here, so no blind spot enters silently.
#
# Every entry below is a `paths:` line that belongs in `unit-tests.yml`. The
# exact replacement text is in the tracking issue.
#
#   .github/workflows/factory-drift.yml — guarded by
#       tests/test_factory_drift_thin_caller_check.py
#   .github/workflows/reusable-pkg-cadence.yml — guarded by
#       tests/test_pkg_cadence_intervals.py
#   .github/workflows/reusable-thin-caller-gate.yml — guarded by
#       tests/test_reusable_thin_caller_gate.py
KNOWN_BLIND: frozenset[str] = frozenset()


def _workflow_basenames() -> set[str]:
    return {path.name for path in WORKFLOW_DIR.glob("*.y*ml")}


def guarded_workflows() -> set[str]:
    """Repo-relative workflow paths that some test module reads or asserts on."""
    on_disk = _workflow_basenames()
    guarded: set[str] = set()
    for module in sorted(TESTS_DIR.glob("test_*.py")):
        if module.name == Path(__file__).name:
            continue
        text = module.read_text(encoding="utf-8")
        for token in _YAML_TOKEN.findall(text):
            if token in on_disk:
                guarded.add(f".github/workflows/{token}")
    return guarded


def _trigger_paths(event: str) -> list[str]:
    workflow = yaml.safe_load(UNIT_TESTS_WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML parses the unquoted `on:` key as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    return list(triggers[event]["paths"])


def _matches(path: str, pattern: str) -> bool:
    """Minimal GitHub path-filter match: exact file, or a `dir/**` prefix."""
    if pattern.endswith("/**"):
        return path.startswith(pattern[: -len("**")])
    return path == pattern


def _covered(path: str, patterns: list[str]) -> bool:
    return any(_matches(path, pattern) for pattern in patterns)


def test_guarded_workflows_are_discovered():
    """The scan must find gates; an empty set would make this file vacuous."""
    guarded = guarded_workflows()
    assert guarded, "no guarded workflow files discovered in tests/"
    assert ".github/workflows/reusable-release-gate.yml" in guarded


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_every_guarded_workflow_triggers_the_unit_test_suite(event):
    patterns = _trigger_paths(event)
    blind = sorted(
        path
        for path in guarded_workflows()
        if not _covered(path, patterns) and path not in KNOWN_BLIND
    )
    assert not blind, (
        f"unit-tests.yml `on.{event}.paths` does not match these workflow files, "
        f"so editing one of them alone never runs the test that guards it: "
        f"{blind}. Add each path to both the push and pull_request `paths:` lists."
    )


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_no_stale_known_blind_spots(event):
    """KNOWN_BLIND is a shrinking ratchet, never a permanent exemption."""
    patterns = _trigger_paths(event)
    fixed = sorted(path for path in KNOWN_BLIND if _covered(path, patterns))
    assert not fixed, (
        f"these paths are now matched by unit-tests.yml `on.{event}.paths`: "
        f"{fixed}. Remove them from KNOWN_BLIND so the gate protects them."
    )


def test_known_blind_spots_are_still_guarded():
    """An entry whose guarding test disappeared must not linger here."""
    stale = sorted(KNOWN_BLIND - guarded_workflows())
    assert not stale, (
        f"KNOWN_BLIND lists workflow files no test guards any more: {stale}. "
        f"Remove them."
    )


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_unit_tests_workflow_triggers_on_itself(event):
    """Narrowing the trigger list must itself re-run this gate."""
    assert _covered(".github/workflows/unit-tests.yml", _trigger_paths(event))
