"""Drift gate: the action roster on disk is the single source of the doc inventories.

Three hand-maintained inventories restate the composite-action roster:

* ``README.md``
* ``docs/skills/composite-actions.md`` (Action catalog table)
* ``docs/skills/composite-actions/action-reference.md``

``docs/consumer-contract.yml`` is deliberately excluded: it records only the
out-of-org consumer surface, not the full roster.
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent

ACTION_ROOTS = (
    ROOT / "bootc-build",
    ROOT / ".github" / "actions",
    ROOT / "actions",
)


def _action_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if (d / "action.yml").is_file())


def all_actions() -> list[Path]:
    return [d for root in ACTION_ROOTS for d in _action_dirs(root)]


def bootc_build_actions() -> list[Path]:
    return _action_dirs(ROOT / "bootc-build")


def _missing(actions: list[Path], text: str, template: str) -> list[str]:
    return [d.name for d in actions if template.format(name=d.name) not in text]


def test_repository_ships_actions():
    assert all_actions(), "no action.yml directories found — roster discovery is broken"


def test_readme_lists_every_action():
    text = (ROOT / "README.md").read_text()
    missing = [
        str(d.relative_to(ROOT))
        for d in all_actions()
        if f"({d.relative_to(ROOT)}/)" not in text
    ]
    assert not missing, f"README.md action tables omit: {missing}"


def test_composite_actions_catalog_lists_every_action():
    text = (ROOT / "docs" / "skills" / "composite-actions.md").read_text()
    missing = _missing(all_actions(), text, "| `{name}` |")
    assert not missing, f"docs/skills/composite-actions.md Action catalog omits: {missing}"


def test_action_reference_documents_every_bootc_build_action():
    reference = ROOT / "docs" / "skills" / "composite-actions" / "action-reference.md"
    text = reference.read_text()
    missing = _missing(bootc_build_actions(), text, "## `{name}`")
    assert not missing, f"action-reference.md has no section for: {missing}"


def test_action_reference_contents_index_matches_its_sections():
    reference = ROOT / "docs" / "skills" / "composite-actions" / "action-reference.md"
    text = reference.read_text()
    missing = _missing(bootc_build_actions(), text, "(#{name})")
    assert not missing, f"action-reference.md Contents index omits: {missing}"


def test_gate_detects_an_undocumented_action(tmp_path, monkeypatch):
    fake = tmp_path / "bootc-build" / "brand-new-action"
    fake.mkdir(parents=True)
    (fake / "action.yml").write_text("name: brand-new-action\n")
    monkeypatch.setattr("tests.test_action_inventory_drift.ROOT", tmp_path)
    monkeypatch.setattr(
        "tests.test_action_inventory_drift.ACTION_ROOTS", (tmp_path / "bootc-build",)
    )
    assert _missing(all_actions(), "", "| `{name}` |") == ["brand-new-action"]
