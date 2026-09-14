"""Tests verifying docs/skills/*.md conform to the canonical skill spec."""
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).parent.parent
SKILLS_DIR = REPO_ROOT / "docs" / "skills"

REQUIRED_SECTIONS = [
    "## When to Use",
    "## When NOT to Use",
    "## Core Process",
    "## Common Rationalizations",
    "## Red Flags",
    "## Verification",
]

def get_all_skill_files():
    return sorted(SKILLS_DIR.glob("**/*.md"))

@pytest.mark.parametrize(
    "skill_file",
    get_all_skill_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_skill_file_has_canonical_sections(skill_file):
    content = skill_file.read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert section in content, (
            f"{skill_file.relative_to(REPO_ROOT)} is missing canonical section: {section}"
        )

@pytest.mark.parametrize(
    "skill_file",
    get_all_skill_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_skill_file_has_use_when_trigger_in_description(skill_file):
    content = skill_file.read_text(encoding="utf-8")
    lines = content.splitlines()[:25]
    desc_lines = [line for line in lines if line.startswith("description:")]
    assert desc_lines, f"{skill_file.relative_to(REPO_ROOT)} is missing frontmatter description"
    desc = desc_lines[0]
    assert "Use when" in desc, (
        f"{skill_file.relative_to(REPO_ROOT)} description should carry 'Use when' trigger phrase: {desc}"
    )
