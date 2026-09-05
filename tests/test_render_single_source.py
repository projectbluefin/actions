"""Guard the single-source-of-truth property of the render entry points.

`scripts/render_pr_body.py` and `scripts/render_gate_section.py` used to be
byte-identical copies of the modules the `render-pr-body` / `render-gate-section`
composite actions execute via `$GITHUB_ACTION_PATH`. Because `tests/conftest.py`
puts `scripts/` first on `sys.path`, the whole suite exercised the `scripts/`
copies while the files that actually run in CI had zero coverage, and nothing
detected drift between the two.

These tests fail if the duplication is ever reintroduced.
"""
from pathlib import Path

import render_gate_section
import render_pr_body

REPO_ROOT = Path(__file__).resolve().parent.parent

CASES = [
    (render_pr_body, "render-pr-body", "render_pr_body", "build_title"),
    (
        render_gate_section,
        "render-gate-section",
        "render_gate_section",
        "build_gate_section",
    ),
]


def _impl_path(action_dir: str, module: str) -> Path:
    return REPO_ROOT / ".github" / "actions" / action_dir / f"{module}.py"


def test_entry_points_execute_the_composite_action_implementation():
    """The imported callables must come from the .github/actions copy."""
    for mod, action_dir, module_name, func_name in CASES:
        func = getattr(mod, func_name)
        assert Path(func.__code__.co_filename) == _impl_path(action_dir, module_name)


def test_entry_points_are_wrappers_not_duplicates():
    """scripts/ entry points must delegate, never restate the implementation."""
    for _, action_dir, module_name, _ in CASES:
        wrapper = (REPO_ROOT / "scripts" / f"{module_name}.py").read_text(encoding="utf-8")
        impl = _impl_path(action_dir, module_name).read_text(encoding="utf-8")
        assert wrapper != impl, f"scripts/{module_name}.py duplicates the implementation"
        assert f"actions/{action_dir}" in wrapper.replace('"', "").replace("\n", "")
        assert len(wrapper.splitlines()) < len(impl.splitlines())
