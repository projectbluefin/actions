"""The renovate-automerge bats heredocs must stay byte-identical to the workflow.

Three bats suites test inline steps of
`.github/workflows/reusable-renovate-automerge.yml` by copying each step's
`run:` block into a heredoc:

* `test_renovate_automerge_find_pr.bats` -> FIND_PR_LOGIC (step id `find-pr`)
* `test_renovate_automerge_checks.bats`  -> CHECKS_LOGIC  (step id `checks`)
* `test_renovate_automerge_merge.bats`   -> MERGE_LOGIC   (step "Merge PR")

A comment saying "verbatim" is not a mechanism. When #649 pinned the merge to
the qualified commit (`--match-head-commit`, the 409 skip, and the head-moved
check in the rollup loop), none of the copies were updated, so the suites kept
passing against the pre-#649 logic and the new guards ran under no test.

This compares each heredoc with the parsed step. It lives in pytest because
`unit-tests.yml` runs the pytest job when the workflow file changes, so editing
the workflow alone is enough to fail this check. Fix a failure by re-copying
the step's `run:` block into the heredoc, then updating the bats tests for any
behaviour that changed.
"""
from pathlib import Path
import re

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-renovate-automerge.yml"
BATS_DIR = REPO_ROOT / "tests" / "bats"

# (bats file, heredoc variable, step selector key, step selector value)
COPIES = [
    ("test_renovate_automerge_find_pr.bats", "FIND_PR_LOGIC", "id", "find-pr"),
    ("test_renovate_automerge_checks.bats", "CHECKS_LOGIC", "id", "checks"),
    ("test_renovate_automerge_merge.bats", "MERGE_LOGIC", "name", "Merge PR"),
]


def _workflow_run(key, value):
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    matches = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get(key) == value and "run" in step
    ]
    assert len(matches) == 1, (
        f"expected exactly one step with {key}={value!r} and a run: block in "
        f"{WORKFLOW.name}, found {len(matches)}. If the step was renamed or "
        "re-id'd, update COPIES here and the bats file header."
    )
    return matches[0].rstrip("\n")


def _bats_copy(bats_name, var):
    text = (BATS_DIR / bats_name).read_text(encoding="utf-8")
    match = re.search(
        rf"^{var}=\$\(cat <<'(\w+)'\n(.*?)\n\1\n\)$", text, re.S | re.M
    )
    assert match, f"{bats_name} no longer defines {var} as a quoted heredoc"
    return match.group(2)


@pytest.mark.parametrize(
    "bats_name,var,key,value", COPIES, ids=[c[1] for c in COPIES]
)
def test_bats_copy_matches_workflow_step(bats_name, var, key, value):
    expected = _workflow_run(key, value)
    actual = _bats_copy(bats_name, var)
    assert actual == expected, (
        f"{var} in tests/bats/{bats_name} has drifted from the {key}={value!r} "
        f"step in {WORKFLOW.name}. The bats suite is testing logic the workflow "
        "no longer runs. Re-copy the step's run: block into the heredoc and "
        "cover any changed behaviour."
    )
