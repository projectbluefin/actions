"""Regression checks for GitHub Actions self-repository composition syntax."""
from pathlib import Path
import re


REPO_ROOT = Path(__file__).parent.parent

# These are implementation-time files. README and docs intentionally show the
# public, cross-repository @v1 interface for consumers.
IMPLEMENTATION_ROOTS = (REPO_ROOT / ".github", REPO_ROOT / "actions", REPO_ROOT / "bootc-build")
SELF_QUALIFIED = re.compile(r"uses:\s+projectbluefin/actions/")
WORKSPACE_RELATIVE = re.compile(
    r"uses:\s+\./(?:\.github/(?:actions|workflows)|actions|bootc-build)/"
)
SELF_REPOSITORY = re.compile(
    r"uses:\s+\$/(?:\.github/(?:actions|workflows)|actions|bootc-build)/"
)


def implementation_uses() -> list[tuple[Path, int, str]]:
    """Return active uses lines from implementation-time YAML files."""
    found = []
    for root in IMPLEMENTATION_ROOTS:
        for path in root.rglob("*.yml"):
            for line_number, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.lstrip()
                if "uses:" in line and not stripped.startswith("#"):
                    found.append((path, line_number, line))
    return found


def test_internal_composition_uses_self_repository_syntax():
    """Internal action/workflow calls must resolve from the running commit."""
    violations = [
        f"{path.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}"
        for path, line_number, line in implementation_uses()
        if SELF_QUALIFIED.search(line) or WORKSPACE_RELATIVE.search(line)
    ]
    assert not violations, "inappropriate self-references remain:\n" + "\n".join(violations)


def test_self_repository_calls_have_expected_shape():
    """Every migrated self-repository call uses the supported $/ prefix."""
    migrated = [
        (path, line_number, line)
        for path, line_number, line in implementation_uses()
        if SELF_REPOSITORY.search(line)
    ]
    assert migrated, "expected migrated self-repository calls"
    assert all("@" not in line.split("#", 1)[0] for _, _, line in migrated)
