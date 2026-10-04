#!/usr/bin/env python3
"""Read-only consumer preflight; run from trusted projectbluefin/actions source.

Usage: python3 scripts/check-issue-onboarding.py --workspace PATH --repository OWNER/REPO
This checks candidate data, not CI, human approval, deployment, or live Prow writes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

# Never import Python from the candidate checkout, including when invoked by path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.issue_policy import validate_catalog
from scripts.prow_commands import validate_config

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required; install pyyaml in the trusted runtime.", file=sys.stderr)
    raise SystemExit(1)

PRODUCTION = "projectbluefin/actions/.github/workflows/reusable-issue-lifecycle.yml@v1"
PREFERENCE_OPTIONS = {"Human interaction only", "Machine analysis is welcome", "No preference"}
EVENTS = {
    "issues": {"opened", "reopened", "edited", "labeled", "unlabeled", "assigned", "unassigned", "closed"},
    "issue_comment": {"created"},
    "pull_request_target": {"opened", "reopened", "ready_for_review", "labeled", "unlabeled", "closed"},
}


class UniqueLoader(yaml.SafeLoader):
    """Reject ambiguous YAML keys rather than silently keeping the last policy."""


def unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def read_data(workspace, relative, *, json_file=False):
    path = workspace / relative
    if not path.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("file resolves outside the caller workspace; replace the symlink with target-owned data")
    text = path.read_text(encoding="utf-8")
    value = json.loads(text, object_pairs_hook=unique_json) if json_file else yaml.load(text, Loader=UniqueLoader)
    if not isinstance(value, dict):
        raise ValueError("expected a mapping/object, not empty or scalar data")
    # Safe YAML still permits dates and recursive aliases; GitHub policy data
    # must be finite JSON-compatible values before any contract comparison.
    json.dumps(value)
    return value


def on_events(workflow):
    return workflow.get("on", workflow.get(True, {}))


def check_intake(forms, catalog):
    errors = []
    if not forms:
        return [".github/ISSUE_TEMPLATE: add native issue forms with a required Automation preference field"]
    bug_headings = []
    feature_headings = []
    for path, form in forms:
        labels = form.get("labels", [])
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            errors.append(f"{path}: labels must be a list of catalog label names")
            continue
        kinds = [label for label in labels if label.startswith("kind/")]
        if len(kinds) != 1 or kinds[0] not in catalog["labels"]:
            errors.append(f"{path}: select exactly one catalog kind/* label; intake cannot infer acceptance")
        unknown = set(labels) - set(catalog["stages"]) - set(catalog["labels"])
        forbidden = set(labels) & (set(catalog["retired_stages"]) | (set(catalog["stages"]) - {"needs-triage"}))
        if unknown or forbidden:
            errors.append(f"{path}: remove unknown/legacy/approval or delivery intake labels: {sorted(unknown | forbidden)}")
        body = form.get("body")
        if not isinstance(body, list) or any(not isinstance(field, dict) for field in body):
            errors.append(f"{path}: body must contain native form fields")
            continue
        preferences = [field for field in body if isinstance(field.get("attributes"), dict)
                       and str(field["attributes"].get("label", "")).strip().lower() == "automation preference"]
        valid = len(preferences) == 1
        if valid:
            preference = preferences[0]
            attributes = preference["attributes"]
            options = attributes.get("options")
            valid = (preference.get("type") == "dropdown"
                     and isinstance(preference.get("validations"), dict)
                     and preference["validations"].get("required") is True
                     and isinstance(options, list) and all(isinstance(value, str) for value in options)
                     and len(options) == 3 and set(options) == PREFERENCE_OPTIONS
                     and attributes.get("multiple", False) is False
                     and "default" not in attributes)
        if not valid:
            errors.append(f"{path}: require one single-choice Automation preference dropdown with Human interaction only, Machine analysis is welcome, No preference; no preselected default")
        headings = {str(field.get("attributes", {}).get("label", "")).strip().lower()
                    for field in body if isinstance(field.get("attributes", {}), dict)}
        if "kind/bug" in labels:
            bug_headings.append((path, headings))
        if "kind/feature" in labels:
            feature_headings.append((path, headings))
    if not bug_headings:
        errors.append(".github/ISSUE_TEMPLATE: provide a native kind/bug intake form")
    for field_type, forms_of_kind in (("bug_fields", bug_headings), ("feature_fields", feature_headings)):
        for path, headings in forms_of_kind:
            required = catalog.get(field_type, [])
            missing = {name.lower() for name in required} - headings
            if not required or missing:
                errors.append(f"{path}: catalog {field_type} do not match emitted headings: {sorted(missing)}")
    return errors


def check_delivery_documentation(workspace, chooser, catalog):
    """Follow the repository's own intake link, not an invented ownership schema."""
    links = chooser.get("contact_links", [])
    lifecycle = [link for link in links if isinstance(link, dict)
                 and "lifecycle" in str(link.get("name", "")).lower()] if isinstance(links, list) else []
    if len(lifecycle) != 1:
        return [".github/ISSUE_TEMPLATE/config.yml: link one target-owned lifecycle document explaining delivery evidence and reporter verification"]
    try:
        url = urlsplit(str(lifecycle[0].get("url", "")))
    except ValueError as error:
        return [f".github/ISSUE_TEMPLATE/config.yml: invalid lifecycle URL: {error}"]
    prefix = f"/{catalog['repository']}/blob/"
    if url.scheme != "https" or url.netloc != "github.com" or not url.path.startswith(prefix):
        return [".github/ISSUE_TEMPLATE/config.yml: lifecycle documentation must belong to the catalog repository, not a shared sidecar"]
    revision_path = url.path[len(prefix):].split("/", 1)
    if len(revision_path) != 2:
        return [".github/ISSUE_TEMPLATE/config.yml: lifecycle link must name a repository document"]
    relative = unquote(revision_path[1])
    path = workspace / relative
    try:
        if not path.resolve().is_relative_to(workspace):
            raise ValueError("lifecycle document resolves outside the caller workspace")
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as error:
        return [f"{relative}: {error}"]
    fields = {"Fix revision", "Release/build", "Verify"}
    fields.update({"Image"} if catalog["delivery"]["type"] == "image" else {"Package", "Version"})
    missing = sorted(field for field in fields if not re.search(rf"^\s*{re.escape(field)}:", text, re.M | re.I))
    errors = []
    if missing:
        errors.append(f"{relative}: document the {catalog['delivery']['type']} delivery receipt fields {missing}; merge alone is not delivery")
    if not re.search(r"\b(?:maintainer|human)\b", text, re.I) or not re.search(r"\breporter\b", text, re.I):
        errors.append(f"{relative}: identify human delivery responsibility and reporter verification responsibility")
    if catalog["delivery"]["type"] == "release" and not (re.search(r"\bhelpers?\b", text, re.I) and re.search(r"\bimage\b", text, re.I)):
        errors.append(f"{relative}: distinguish app release delivery from separately image-installed helper delivery")
    return errors


def check_caller(path, workflow, catalog):
    errors = []
    events = on_events(workflow)
    if not isinstance(events, dict):
        return [f"{path}: lifecycle caller must declare typed events and explicit manual read-only defaults"]
    for event, required in EVENTS.items():
        config = events.get(event)
        types = config.get("types", []) if isinstance(config, dict) else []
        if not isinstance(types, list) or any(not isinstance(value, str) for value in types) or not required <= set(types):
            errors.append(f"{path}: {event}.types must include {', '.join(sorted(required))}")
    if not isinstance(events.get("schedule"), list) or not events["schedule"]:
        errors.append(f"{path}: add a scheduled reconciliation sweep for bot-label event cascades")
    dispatch = events.get("workflow_dispatch")
    inputs = dispatch.get("inputs", {}) if isinstance(dispatch, dict) else {}
    apply = inputs.get("apply", {}) if isinstance(inputs, dict) else {}
    if not isinstance(apply, dict) or apply.get("type") != "boolean" or apply.get("default") is not False:
        errors.append(f"{path}: workflow_dispatch.inputs.apply must be boolean with default false; manual runs preview first")
    jobs = workflow.get("jobs", {})
    lifecycle_jobs = [(name, job) for name, job in jobs.items() if isinstance(job, dict) and job.get("uses") == PRODUCTION] if isinstance(jobs, dict) else []
    if len(lifecycle_jobs) != 1:
        errors.append(f"{path}: use exactly one released {PRODUCTION} job; feature runtime refs are preview-only")
        return errors
    name, job = lifecycle_jobs[0]
    prefix = f"{path}: jobs.{name}"
    permission = job.get("permissions", workflow.get("permissions", {}))
    required_permissions = {"contents": "read", "actions": "read", "issues": "write", "pull-requests": "write"}
    if permission != required_permissions:
        errors.append(f"{prefix}: grant only contents: read, actions: read, issues: write, pull-requests: write")
    repository_guard = f"github.repository == '{catalog['repository']}'"
    if str(job.get("if", "")).strip().removeprefix("${{").removesuffix("}}").strip() != repository_guard:
        errors.append(f"{prefix}: guard the production job with {repository_guard}")
    if "secrets" in job or "steps" in job:
        errors.append(f"{prefix}: the shared production caller needs no secrets or caller steps")
    options = job.get("with", {})
    production_apply = options.get("apply") if isinstance(options, dict) else None
    allowed_apply = {"${{ github.event_name != 'workflow_dispatch' || inputs.apply }}", False}
    if not isinstance(production_apply, (str, bool)) or production_apply not in allowed_apply:
        errors.append(f"{prefix}: apply must be false or ${{{{ github.event_name != 'workflow_dispatch' || inputs.apply }}}}; do not make manual previews write by default")
    return errors


def competing_workflow(path, workflow, catalog):
    """Catch known old writers/dispatchers; this is not an arbitrary-code audit."""
    errors = []
    text = json.dumps(workflow)
    legacy = ("common_issue_policy.py", "reusable-design-enforcement.yml", "issue-pipeline.yml",
              "on-issue-opened", "projectbluefin/actions/.github/workflows/lifecycle.yml")
    if any(marker in text for marker in legacy):
        errors.append(f"{path}: remove the competing legacy lifecycle/stage writer before enabling the shared lifecycle")
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        errors.append(f"{path}: jobs must be a mapping")
        return errors
    for name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps", [])
        executable = json.dumps(steps)
        stage_names = set(catalog["stages"]) | set(catalog["retired_stages"])
        has_stage = any(label in executable for label in stage_names)
        mutations = re.search(r"add-label|remove-label|addLabels|removeLabels|issues\.addLabels|issues\.removeLabel|labeler|/labels|--method[ =]+(?:POST|PATCH|DELETE)", executable, re.I)
        if has_stage and mutations:
            errors.append(f"{path}: jobs.{name} independently mutates lifecycle stages; retain one shared stage writer")
        label_trigger = "event.label" in str(job.get("if", "")) or "ai-fix-requested" in text or "3-clanker-queue" in str(job.get("if", ""))
        dispatch = re.search(r"assign_copilot|assignCopilot|copilot-swe-agent|workflow_dispatch|createWorkflowDispatch|gh workflow run|/dispatches", executable + str(job.get("uses", "")), re.I)
        if label_trigger and dispatch:
            errors.append(f"{path}: jobs.{name} dispatches implementation from labels alone; use explicit acceptance and native assignment")
    return errors


def check_workspace(workspace, repository=None):
    """Return actionable errors without running caller code or contacting GitHub."""
    workspace = Path(workspace).resolve()
    errors = []

    def load(relative, **kwargs):
        try:
            return read_data(workspace, relative, **kwargs)
        except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
            errors.append(f"{relative}: {error}")
            return None

    catalog = load(".github/issue-policy.json", json_file=True)
    if catalog is None:
        return errors
    try:
        validate_catalog(catalog, repository)
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        return [*errors, f".github/issue-policy.json: {error}; correct the target-owned catalog, do not generate approvals"]
    if not catalog.get("main_ci_workflows"):
        errors.append(".github/issue-policy.json: declare native main_ci_workflows; deployed writes require actual current-main CI success")
    prow = load(".github/prow.yaml")
    if prow is not None:
        try:
            validate_config(catalog, prow)
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            errors.append(f".github/prow.yaml: does not match prow_commands.expected_config(catalog): {error}")
    chooser = load(".github/ISSUE_TEMPLATE/config.yml")
    if chooser is not None:
        errors.extend(check_delivery_documentation(workspace, chooser, catalog))
    forms = []
    for path in sorted((workspace / ".github/ISSUE_TEMPLATE").glob("*")):
        if path.suffix not in {".yml", ".yaml"} or path.stem == "config":
            continue
        relative = path.relative_to(workspace).as_posix()
        form = load(relative)
        if form is not None:
            forms.append((relative, form))
    errors.extend(check_intake(forms, catalog))
    workflows = []
    for path in sorted((workspace / ".github/workflows").glob("*")):
        if path.suffix not in {".yml", ".yaml"}:
            continue
        relative = path.relative_to(workspace).as_posix()
        workflow = load(relative)
        if workflow is not None:
            workflows.append((relative, workflow))
            errors.extend(competing_workflow(relative, workflow, catalog))
    callers = [(path, workflow) for path, workflow in workflows
               if "projectbluefin/actions/.github/workflows/reusable-issue-lifecycle.yml@" in json.dumps(workflow)]
    if len(callers) != 1:
        errors.append(".github/workflows: provide exactly one thin reusable-issue-lifecycle.yml@v1 production caller; preview workflows are not production callers")
    else:
        errors.extend(check_caller(*callers[0], catalog))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="caller repository checkout, read as data only")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"), help="expected target owner/repo (defaults to GITHUB_REPOSITORY)")
    args = parser.parse_args(argv)
    errors = check_workspace(args.workspace, args.repository)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Onboarding preflight passed: target catalog, constrained Prow, native intake, and single production caller.")
    print("Read-only candidate validation is not human acceptance, CI/deployment approval, or live Prow write proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
