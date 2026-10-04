"""Consumer data/safety failures for the read-only onboarding CLI."""
from copy import deepcopy
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest
import yaml

from scripts.prow_commands import expected_config

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-issue-onboarding.py"
check_workspace = runpy.run_path(str(SCRIPT))["check_workspace"]


def save(workspace, relative, value):
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if path.suffix == ".json" else yaml.safe_dump(value), encoding="utf-8")


@pytest.fixture
def consumer(tmp_path):
    definition = {"color": "abcdef", "description": "Repository-owned label"}
    catalog = {
        "repository": "projectbluefin/example",
        "display_name": "Example",
        "comment_marker": "<!-- example-lifecycle:v1 -->",
        "delivery": {"type": "image"},
        "stages": {name: deepcopy(definition) for name in (
            "needs-triage", "triage/needs-information", "triage/accepted", "awaiting-release", "needs-verification")},
        "labels": {name: deepcopy(definition) for name in (
            "kind/bug", "kind/feature", "kind/task", "area/ui", "needs-kind", "needs-human", "human-only", "tracking", "hold", "blocked")},
        "retired_stages": ["3-clanker-queue", "3-human-queue"],
        "standing_issues": [],
        "label_aliases": {},
        "bug_fields": ["what happened?"],
        "main_ci_workflows": [".github/workflows/ci.yml"],
    }
    form = {
        "name": "Bug", "description": "Report a problem", "labels": ["needs-triage", "kind/bug"],
        "body": [
            {"type": "dropdown", "id": "automation", "attributes": {
                "label": "Automation preference", "options": ["Human interaction only", "Machine analysis is welcome", "No preference"]},
             "validations": {"required": True}},
            {"type": "textarea", "id": "problem", "attributes": {"label": "What happened?"}, "validations": {"required": True}},
        ],
    }
    caller = {
        "name": "Issue lifecycle", "on": {
            "issues": {"types": ["opened", "reopened", "edited", "labeled", "unlabeled", "assigned", "unassigned", "closed"]},
            "issue_comment": {"types": ["created"]},
            "pull_request_target": {"types": ["opened", "reopened", "ready_for_review", "labeled", "unlabeled", "closed"]},
            "schedule": [{"cron": "17 * * * *"}],
            "workflow_dispatch": {"inputs": {"apply": {"type": "boolean", "default": False}}},
        },
        "permissions": {}, "jobs": {"reconcile": {
            "if": "github.repository == 'projectbluefin/example'",
            "permissions": {"contents": "read", "actions": "read", "issues": "write", "pull-requests": "write"},
            "uses": "projectbluefin/actions/.github/workflows/reusable-issue-lifecycle.yml@v1",
            "with": {"apply": "${{ github.event_name != 'workflow_dispatch' || inputs.apply }}"},
        }},
    }
    chooser = {"blank_issues_enabled": True, "contact_links": [{
        "name": "Example issue lifecycle", "url": "https://github.com/projectbluefin/example/blob/main/docs/lifecycle.md"}]}
    save(tmp_path, ".github/issue-policy.json", catalog)
    save(tmp_path, ".github/prow.yaml", expected_config(catalog))
    save(tmp_path, ".github/ISSUE_TEMPLATE/bug.yml", form)
    save(tmp_path, ".github/ISSUE_TEMPLATE/config.yml", chooser)
    save(tmp_path, ".github/workflows/issues.yml", caller)
    document = tmp_path / "docs/lifecycle.md"
    document.parent.mkdir()
    document.write_text("A maintainer records image delivery. The reporter verifies the installed fix.\n"
                        "Image: delivered image and digest\nFix revision: full commit\nRelease/build: published run\nVerify: update and reproduce\n")
    return tmp_path, catalog, form, caller


def failures(consumer):
    return "\n".join(check_workspace(consumer[0], "projectbluefin/example"))


def test_valid_candidate_is_read_only_and_does_not_run_caller_code(consumer):
    workspace = consumer[0]
    scripts = workspace / "scripts"
    scripts.mkdir()
    (scripts / "__init__.py").write_text("raise RuntimeError('untrusted caller module executed')\n")
    (workspace / "setup.py").write_text("raise RuntimeError('untrusted caller setup executed')\n")
    before = {path.relative_to(workspace): path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--workspace", str(workspace), "--repository", "projectbluefin/example"],
        cwd=workspace, env={**os.environ, "PYTHONPATH": str(workspace)}, capture_output=True, text=True, check=False,
    )
    after = {path.relative_to(workspace): path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    assert result.returncode == 0, result.stderr
    assert after == before


def test_repository_mismatch_is_refused(consumer):
    errors = check_workspace(consumer[0], "projectbluefin/different")
    assert any("repository mismatch" in error for error in errors)


@pytest.mark.parametrize("change", [
    lambda c: c["label_aliases"].update({"old-approval": "triage/accepted"}),
    lambda c: c["stages"].pop("needs-verification"),
    lambda c: c.update(delivery={"type": "guess"}),
])
def test_invalid_runtime_catalog_is_not_accepted(consumer, change):
    workspace, catalog, _, _ = consumer
    change(catalog)
    save(workspace, ".github/issue-policy.json", catalog)
    assert ".github/issue-policy.json" in failures(consumer)


@pytest.mark.parametrize("change", [
    lambda p: p["tide"].update(merge_on_events=True),
    lambda p: p["tide"].update(merge_on_events=0),
    lambda p: p["labels"].update(triage={"values": ["accepted"], "exclusive": True}),
    lambda p: p["labels"]["kind"].update(exclusive=False),
    lambda p: p.update(approve={"enabled": True}),
])
def test_prow_privilege_and_cardinality_drift_is_refused(consumer, change):
    workspace, catalog, _, _ = consumer
    prow = expected_config(catalog)
    change(prow)
    save(workspace, ".github/prow.yaml", prow)
    assert ".github/prow.yaml: does not match" in failures(consumer)


@pytest.mark.parametrize("change", [
    lambda f: f["body"][0]["validations"].update(required=False),
    lambda f: f["body"][0]["attributes"].update(default=1),
    lambda f: f["body"][0]["attributes"].update(options=["Allow AI implementation"]),
    lambda f: f["body"][0]["attributes"].update(multiple=True),
])
def test_native_preference_is_explicit_and_not_preselected(consumer, change):
    workspace, _, form, _ = consumer
    change(form)
    save(workspace, ".github/ISSUE_TEMPLATE/bug.yml", form)
    assert "Automation preference dropdown" in failures(consumer)


@pytest.mark.parametrize("labels", [["kind/bug", "triage/accepted"], ["kind/bug", "3-clanker-queue"], ["kind/bug", "kind/task"]])
def test_intake_cannot_grant_approval_or_ambiguous_kind(consumer, labels):
    workspace, _, form, _ = consumer
    form["labels"] = labels
    save(workspace, ".github/ISSUE_TEMPLATE/bug.yml", form)
    assert failures(consumer)


def test_bug_receipt_headings_match_native_form(consumer):
    workspace, catalog, _, _ = consumer
    catalog["bug_fields"] = ["image from the old form"]
    save(workspace, ".github/issue-policy.json", catalog)
    assert "bug_fields do not match" in failures(consumer)


@pytest.mark.parametrize("change, message", [
    (lambda c: c["on"]["issues"]["types"].remove("unlabeled"), "issues.types"),
    (lambda c: c["on"]["workflow_dispatch"]["inputs"]["apply"].update(default=True), "default false"),
    (lambda c: c["jobs"]["reconcile"]["with"].update(apply=True), "manual previews"),
    (lambda c: c["jobs"]["reconcile"].update(secrets="inherit"), "needs no secrets"),
    (lambda c: c["jobs"]["reconcile"]["permissions"].update(contents="write"), "grant only"),
    (lambda c: c["jobs"]["reconcile"].update(uses="projectbluefin/actions/.github/workflows/reusable-issue-lifecycle.yml@feat/shared-issue-onboarding"), "preview-only"),
])
def test_production_event_and_write_safety_contract(consumer, change, message):
    workspace, _, _, caller = consumer
    change(caller)
    save(workspace, ".github/workflows/issues.yml", caller)
    assert message in failures(consumer)


def test_competing_stage_writer_is_refused(consumer):
    save(consumer[0], ".github/workflows/old.yml", {"on": {"issues": {"types": ["opened"]}}, "jobs": {
        "old": {"steps": [{"run": "gh issue edit 1 --add-label triage/accepted"}]}}})
    assert "independently mutates lifecycle stages" in failures(consumer)


def test_label_only_implementation_dispatch_is_refused(consumer):
    save(consumer[0], ".github/workflows/dispatch.yml", {"on": {"issues": {"types": ["labeled"]}}, "jobs": {
        "dispatch": {"if": "github.event.label.name == 'ai-fix-requested'", "steps": [{"run": "gh workflow run implement.yml"}]}}})
    assert "dispatches implementation from labels alone" in failures(consumer)


def test_missing_or_wrong_repository_delivery_document_is_refused(consumer):
    save(consumer[0], ".github/ISSUE_TEMPLATE/config.yml", {"contact_links": [{
        "name": "Issue lifecycle", "url": "https://github.com/projectbluefin/common/blob/main/docs/lifecycle.md"}]})
    assert "must belong to the catalog repository" in failures(consumer)


def test_application_delivery_requires_application_receipt_and_helper_boundary(consumer):
    workspace, catalog, _, _ = consumer
    catalog["delivery"]["type"] = "release"
    save(workspace, ".github/issue-policy.json", catalog)
    errors = failures(consumer)
    assert "Package" in errors and "Version" in errors
    assert "image-installed helper delivery" in errors
    (workspace / "docs/lifecycle.md").write_text(
        "A maintainer records app release and separately image-installed helper delivery. The reporter verifies.\n"
        "Package: cask\nVersion: published version\nFix revision: full commit\nRelease/build: release\nVerify: update and reproduce\n")
    assert not failures(consumer)


def test_external_catalog_symlink_is_refused(consumer, tmp_path_factory):
    workspace, catalog, _, _ = consumer
    external = tmp_path_factory.mktemp("outside") / "catalog.json"
    external.write_text(json.dumps(catalog))
    path = workspace / ".github/issue-policy.json"
    path.unlink()
    path.symlink_to(external)
    assert "resolves outside the caller workspace" in failures(consumer)


@pytest.mark.parametrize("content", ["tide: {merge_on_events: false}\ntide: {merge_on_events: true}\n", "!!python/object/apply:os.system ['touch unexpected']\n", "[]\n"])
def test_ambiguous_or_executable_yaml_is_data_error(consumer, content):
    (consumer[0] / ".github/prow.yaml").write_text(content)
    assert ".github/prow.yaml" in failures(consumer)


def test_malformed_catalog_reports_actionable_cli_failure(consumer):
    (consumer[0] / ".github/issue-policy.json").write_text("{broken")
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--workspace", str(consumer[0])],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert ".github/issue-policy.json" in result.stderr
    assert "Traceback" not in result.stderr


def test_duplicate_catalog_repository_is_actionable_data_error(consumer):
    path = consumer[0] / ".github/issue-policy.json"
    path.write_text('{"repository":"projectbluefin/example","repository":"projectbluefin/other"}')
    assert "duplicate JSON key" in failures(consumer)


def test_known_legacy_lifecycle_cannot_coexist_with_shared_writer(consumer):
    save(consumer[0], ".github/workflows/legacy.yml", {"on": {"issues": {"types": ["opened"]}}, "jobs": {
        "legacy": {"uses": "projectbluefin/actions/.github/workflows/reusable-design-enforcement.yml@v1"}}})
    assert "competing legacy lifecycle/stage writer" in failures(consumer)


def test_feature_form_must_match_consumer_required_headings(consumer):
    workspace, catalog, form, caller = consumer
    catalog["feature_fields"] = ["problem to solve", "proposed outcome"]
    feature = deepcopy(form)
    feature["labels"] = ["needs-triage", "kind/feature"]
    feature["body"][1]["attributes"]["label"] = "Problem to solve"
    outcome = deepcopy(feature["body"][1])
    outcome["id"] = "outcome"
    outcome["attributes"]["label"] = "Proposed outcome"
    feature["body"].append(outcome)
    save(workspace, ".github/issue-policy.json", catalog)
    save(workspace, ".github/ISSUE_TEMPLATE/feature.yml", feature)
    assert failures(consumer) == ""
    feature["body"][-1]["attributes"]["label"] = "Desired outcome"
    save(workspace, ".github/ISSUE_TEMPLATE/feature.yml", feature)
    assert "feature_fields do not match emitted headings" in failures(consumer)


@pytest.mark.parametrize("signal", ["kind/tech-debt", "source:agent", "Kind/Tech-Debt"])
def test_native_intake_cannot_assign_protected_operational_signal(consumer, signal):
    workspace, catalog, form, _ = consumer
    catalog["protected_labels"] = ["kind/tech-debt", "source:agent"]
    save(workspace, ".github/issue-policy.json", catalog)
    assert failures(consumer) == ""
    form["labels"].append(signal)
    save(workspace, ".github/ISSUE_TEMPLATE/bug.yml", form)
    assert "operational" in failures(consumer)


def test_catalog_cannot_retire_or_sync_protected_operational_definitions(consumer):
    workspace, catalog, _, _ = consumer
    catalog["protected_labels"] = ["kind/tech-debt", "source:agent"]
    catalog["retired_stages"].append("kind/tech-debt")
    save(workspace, ".github/issue-policy.json", catalog)
    assert "Retired" in failures(consumer)
    catalog["retired_stages"].remove("kind/tech-debt")
    catalog["labels"]["source:agent"] = {"color": "abcdef", "description": "Guessed operator definition"}
    save(workspace, ".github/issue-policy.json", catalog)
    assert "protected_labels" in failures(consumer)
