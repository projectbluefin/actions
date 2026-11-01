"""Keep .github/zizmor.yml pointed at the lines it baselines.

zizmor ignores are keyed by ``file:line``. When a workflow gains or loses lines
above a pinned site, the pin silently stops matching: the baseline no longer
suppresses the finding (the check goes red on an unrelated PR) and, worse, it
may start suppressing whatever now sits at that line. #688 was one such drift;
the merge_note input added by #680 was another. Each pinned line must still
carry the construct the rule audits, and every named file must still exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[1]
BASELINE = REPO_ROOT / ".github" / "zizmor.yml"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# What zizmor anchors each rule's finding on, so a pin that no longer lands on
# such a line is a drifted pin rather than a baselined finding.
RULE_LINE_MARKERS = {
    "template-injection": re.compile(r"\$\{\{"),
    "secrets-inherit": re.compile(r"^\s*uses:\s"),
    "excessive-permissions": re.compile(r"^\s*[a-z-]+:\s*(read|write)\b|^\s*permissions:"),
    "github-app": re.compile(r"create-github-app-token|^\s*owner:"),
}


def _ignores():
    rules = yaml.safe_load(BASELINE.read_text())["rules"]
    for rule, config in rules.items():
        for entry in config.get("ignore", []):
            yield rule, str(entry)


ENTRIES = list(_ignores())


@pytest.mark.parametrize("rule,entry", ENTRIES, ids=[f"{r}:{e}" for r, e in ENTRIES])
def test_baselined_file_exists(rule, entry):
    filename = entry.split(":", 1)[0]
    assert (WORKFLOWS / filename).is_file(), (
        f"{entry} ({rule}) names a workflow that no longer exists; drop the entry"
    )


@pytest.mark.parametrize(
    "rule,entry",
    [(r, e) for r, e in ENTRIES if ":" in e],
    ids=[f"{r}:{e}" for r, e in ENTRIES if ":" in e],
)
def test_pinned_line_still_carries_the_audited_construct(rule, entry):
    filename, line_no = entry.split(":", 1)
    marker = RULE_LINE_MARKERS.get(rule)
    assert marker is not None, f"no line marker known for rule {rule}; add one"

    lines = (WORKFLOWS / filename).read_text().splitlines()
    index = int(line_no) - 1
    assert 0 <= index < len(lines), f"{entry} points past the end of the file"

    line = lines[index]
    assert marker.search(line), (
        f"{entry} ({rule}) no longer points at an audited site. Line reads:\n"
        f"    {line.strip()!r}\n"
        "Re-run `zizmor --offline --no-config --min-severity=medium "
        "--min-confidence=medium .` and move the pin to the reported line."
    )
