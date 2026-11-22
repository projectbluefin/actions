"""The create-release bats heredocs must stay byte-identical to the action.

`tests/bats/test_create_release.bats` tests the inline shell steps of
`bootc-build/create-release/action.yml` by copying each step's `run:` block
into a heredoc. When #749 stopped attaching the release card PNGs when the
card could not be drawn, the copies of "Render release card" and "Create
GitHub Release" were not updated, so the suite kept asserting the old
always-attach behaviour and the new gating ran under no test.

This compares each heredoc with the parsed step. Fix a failure by re-copying
the step's `run:` block into the heredoc, then updating the bats tests for any
behaviour that changed.
"""
from pathlib import Path
import re

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
ACTION = REPO_ROOT / "bootc-build" / "create-release" / "action.yml"
BATS = REPO_ROOT / "tests" / "bats" / "test_create_release.bats"

# (heredoc variable, step name)
COPIES = [
    ("VALIDATE_SBOM_LOGIC", "Validate SBOM"),
    ("PREV_SBOM_LOGIC", "Fetch previous SBOM"),
    ("OPTIONAL_INPUTS_LOGIC", "Write optional inputs to disk"),
    ("RENDER_CARD_LOGIC", "Render release card"),
    ("SBOM_NAME_LOGIC", "Resolve SBOM filename"),
    ("OVERFLOW_LOGIC", "Detect overflow notes"),
    ("CREATE_RELEASE_LOGIC", "Create GitHub Release"),
]


def _action_run(name):
    action = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    matches = [
        step["run"]
        for step in action["runs"]["steps"]
        if step.get("name") == name and "run" in step
    ]
    assert len(matches) == 1, (
        f"expected exactly one step named {name!r} with a run: block in "
        f"{ACTION.relative_to(REPO_ROOT)}, found {len(matches)}. If the step "
        "was renamed, update COPIES here and the bats file."
    )
    return matches[0].rstrip("\n")


def _bats_copy(var):
    text = BATS.read_text(encoding="utf-8")
    match = re.search(
        rf"^{var}=\$\(cat <<'(\w+)'\n(.*?)\n\1\n\)$", text, re.S | re.M
    )
    assert match, f"{BATS.name} no longer defines {var} as a quoted heredoc"
    return match.group(2)


def test_every_heredoc_is_checked():
    defined = set(re.findall(r"^(\w+_LOGIC)=\$\(cat <<'", BATS.read_text(encoding="utf-8"), re.M))
    assert defined == {var for var, _ in COPIES}, (
        f"{BATS.name} heredocs and COPIES disagree; add new copies to COPIES"
    )


@pytest.mark.parametrize("var,name", COPIES, ids=[c[0] for c in COPIES])
def test_bats_copy_matches_action_step(var, name):
    assert _bats_copy(var) == _action_run(name), (
        f"{var} in tests/bats/{BATS.name} has drifted from the {name!r} step "
        f"in {ACTION.relative_to(REPO_ROOT)}. The bats suite is testing logic "
        "the action no longer runs. Re-copy the step's run: block into the "
        "heredoc and cover any changed behaviour."
    )
