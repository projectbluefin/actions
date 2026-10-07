#!/usr/bin/env python3
"""Reconcile catalog-bound issues and PRs; dry-run unless trusted Actions applies."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import json
from datetime import datetime, timezone
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from scripts.issue_status import status_report
from uuid import uuid4

ACTION_REPOSITORY = "projectbluefin/actions"
ACTION_REF = "v1"
STAGES = {"needs-triage", "triage/needs-information", "triage/accepted", "awaiting-release", "needs-verification"}
SOURCE_FILES = ("scripts/issue_policy.py", "scripts/issue_status.py", "issue-lifecycle/action.yml",
                "scripts/prow_commands.py", "prow-labels/action.yml",
                ".github/workflows/reusable-issue-lifecycle.yml")
EMPTY = {"", "_no response_", "no response", "none"}
# Default-branch CI usually finishes within minutes of a merge; the reusable
# lifecycle job has a 15-minute timeout, so the wait must leave room for the rest.
MAIN_CI_WAIT_SECONDS = 600
MAIN_CI_POLL_SECONDS = 30


class StaleRecord(RuntimeError):
    """A human changed this record; skip it rather than overwrite that work."""


class MainCIPending(RuntimeError):
    """Main CI is still running: nothing is authorized, and the event is deferred."""


def protected_labels(catalog):
    """Exact operator-owned names, compared like GitHub labels, never managed here."""
    return {name.lower() for name in catalog.get("protected_labels", [])}


def validate_catalog(catalog, repository=None):
    """Bind configuration to a single repository before reading or writing records."""
    repo = catalog.get("repository", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or repo.lower().startswith("ublue-os/"):
        raise ValueError("Invalid or prohibited catalog repository")
    if repository is not None and repository != repo:
        raise ValueError(f"Catalog only writes {repo}; repository mismatch")
    if set(catalog.get("stages", {})) != STAGES:
        raise ValueError("Catalog must define the five lifecycle stages")
    if not isinstance(catalog.get("display_name"), str) or not catalog["display_name"].strip():
        raise ValueError("Catalog requires display_name")
    if not re.fullmatch(r"<!-- [A-Za-z0-9_.:-]+ -->", catalog.get("comment_marker", "")):
        raise ValueError("Catalog requires a unique hidden comment_marker")
    if catalog.get("delivery", {}).get("type") not in {"image", "release"}:
        raise ValueError("Catalog delivery.type must be image or release")
    labels = catalog.get("labels", {})
    required = {"kind/bug", "kind/feature", "kind/task", "needs-kind", "needs-human", "human-only", "tracking"}
    if not required <= set(labels) or set(labels) & STAGES:
        raise ValueError("Catalog is missing lifecycle gate/classification definitions")
    for name, definition in (catalog["stages"] | labels).items():
        if not isinstance(name, str) or not name or not isinstance(definition, dict) or set(definition) != {"color", "description"}:
            raise ValueError("Invalid catalog label definition")
        if not re.fullmatch(r"[0-9a-fA-F]{6}", definition["color"]) or not isinstance(definition["description"], str):
            raise ValueError("Invalid label color or description")
    signals = catalog.get("protected_labels", [])
    if not isinstance(signals, list) or any(not isinstance(name, str) or not name for name in signals):
        raise ValueError("protected_labels must explicitly list independent operational label names")
    unmanaged = protected_labels(catalog)
    if len(unmanaged) != len(signals) or unmanaged & {name.lower() for name in catalog["stages"] | labels}:
        raise ValueError("protected_labels must be unique and outside managed catalog definitions")
    retired = catalog.get("retired_stages")
    if not isinstance(retired, list) or any(not isinstance(n, str) or not n for n in retired) or set(retired) & set(catalog["stages"] | labels) or any(name.lower() in unmanaged for name in retired):
        raise ValueError("Retired labels must not overlap canonical definitions or protected operational labels")
    if not isinstance(catalog.get("standing_issues"), list) or any(type(n) is not int or n < 1 for n in catalog["standing_issues"]):
        raise ValueError("Invalid standing issue numbers")
    aliases = catalog.get("label_aliases")
    if not isinstance(aliases, dict):
        raise ValueError("Catalog requires explicit label_aliases")
    protected = STAGES | {"blocked", "hold", "needs-human", "human-only", "needs-kind", "tracking", "lgtm", "automerge"} | unmanaged
    for old, new in aliases.items():
        if not isinstance(old, str) or not old or old.lower() in protected or old.startswith(("agent/", "hive/")) or old in set(catalog["stages"] | labels):
            raise ValueError("Alias cannot retire a canonical or independent operational label")
        if new is not None and (new not in labels or new.lower() in protected or not new.startswith(("kind/", "area/"))):
            raise ValueError("Aliases may only map descriptive labels, never grant a lifecycle stage or gate")
    sources = catalog.get("kind_sources", {})
    if not isinstance(sources, dict) or any(
        old not in labels or old.startswith("kind/") or not isinstance(new, str)
        or new not in labels or not new.startswith("kind/")
        for old, new in sources.items()
    ):
        raise ValueError("kind_sources must map existing operational labels to catalog kinds")
    gates = catalog.get("gate_labels", [])
    if not isinstance(gates, list) or any(not isinstance(name, str) or name not in labels for name in gates):
        raise ValueError("gate_labels must name existing independent catalog labels")
    for field_type in ("bug_fields", "feature_fields"):
        field_names = catalog.get(field_type, [])
        if not isinstance(field_names, list) or any(not isinstance(name, str) or not name.strip() for name in field_names):
            raise ValueError(f"{field_type} must name the repository's issue-form headings")
    prior_markers = catalog.get("prior_comment_markers", [])
    if not isinstance(prior_markers, list) or any(
        not isinstance(marker, str) or not re.fullmatch(r"<!-- [A-Za-z0-9_.:-]+ -->", marker)
        for marker in prior_markers
    ):
        raise ValueError("prior_comment_markers must be explicit hidden lifecycle markers")
    workflows = catalog.get("main_ci_workflows", [])
    if not isinstance(workflows, list) or any(
        not isinstance(path, str) or not re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", path)
        for path in workflows
    ):
        raise ValueError("main_ci_workflows must name repository-owned CI workflow paths")
    intake_rules = catalog.get("intake_rules", [])
    if not isinstance(intake_rules, list) or len(intake_rules) > 64:
        raise ValueError("intake_rules must be a bounded list of descriptive metadata rules")
    protected_intake = protected | set(retired) | set(gates) | {"ai-fix-requested"}
    for rule in intake_rules:
        if not isinstance(rule, dict) or set(rule) != {"match", "labels"}:
            raise ValueError("intake_rules require match selectors and metadata labels only")
        selectors, targets = rule["match"], rule["labels"]
        if not isinstance(selectors, dict) or not selectors or not set(selectors) <= {"title_prefixes", "body_contains", "body_headings"}:
            raise ValueError("Unsupported intake selector; use literal title prefixes, body text or headings")
        for values in selectors.values():
            if not isinstance(values, list) or not 1 <= len(values) <= 16 or any(
                not isinstance(value, str) or not value.strip() or len(value) > 256 for value in values
            ):
                raise ValueError("Intake selectors must be bounded nonempty literal strings")
        if not isinstance(targets, list) or not 1 <= len(targets) <= 8 or any(
            not isinstance(name, str) or name not in labels or name in protected_intake or name.lower() in unmanaged
            or name.startswith(("needs-", "hive/", "queue/", "status/")) for name in targets
        ):
            raise ValueError("Intake targets must be catalog metadata, never stages, consent, dispatch or independent control labels")
    return catalog


def lifecycle_bot(value):
    return value.get("type") == "Bot" and value.get("login") == "github-actions[bot]"


def authorized_stage_event(timeline, facts, label):
    """Choose the human grant before latest selection; projections are not consent."""
    humans = [e for e in timeline if trusted_event(e, facts)]
    grant = latest_event(humans, label)
    withdrawal = latest_event(humans, label, "unlabeled")
    if not grant or (withdrawal and event_order(withdrawal) > event_order(grant)):
        return None
    if label in {"awaiting-release", "needs-verification"}:
        if "last_edited_at" not in facts or (facts["last_edited_at"] and facts["last_edited_at"] >= grant["created_at"]):
            return None
        resets = [latest_event(timeline, reset) for reset in ("needs-triage", "triage/needs-information")]
        if any(reset and event_order(reset) > event_order(grant) for reset in resets):
            return None
    return grant


def request_identity(event, record):
    if event:
        return f"{event.get('id', '')}:{event.get('created_at', '')}:{(event.get('label') or {}).get('name', '')}"
    # The first automatic information request has no timeline event until applied.
    # A stable initial identity prevents its subsequent projection from re-notifying.
    return f"initial:{record['number']}"


def headings(body):
    matches = list(re.finditer(r"^#{2,6}\s+(.+?)\s*$", body or "", re.M))
    return {
        match[1].lower(): (
            body[
                match.end() : matches[i + 1].start()
                if i + 1 < len(matches)
                else len(body)
            ]
        ).strip()
        for i, match in enumerate(matches)
    }


def labels_of(record):
    return {
        label if isinstance(label, str) else label["name"]
        for label in record.get("labels", [])
    }


def event_order(event):
    return (event.get("created_at", ""), event.get("id") or 0)


def latest_event(timeline, label, event="labeled"):
    matches = [
        e
        for e in timeline
        if e.get("event") == event and (e.get("label") or {}).get("name") == label
    ]
    return max(matches, key=event_order, default=None)


def trusted_event(event, facts):
    if not event:
        return False
    actor = event.get("actor") or {}
    return actor.get("type") == "User" and facts.get("permissions", {}).get(
        actor.get("login")
    ) in {"write", "maintain", "admin"}


def approved_scope(timeline, facts):
    human_events = [e for e in timeline if trusted_event(e, facts)]
    event = latest_event(human_events, "triage/accepted")
    if not event or "last_edited_at" not in facts:
        return False
    if facts["last_edited_at"] and facts["last_edited_at"] >= event["created_at"]:
        return False
    withdrawal = latest_event(human_events, "triage/accepted", "unlabeled")
    if withdrawal and event_order(withdrawal) > event_order(event):
        return False
    # Returning to assessment or information gathering invalidates that grant,
    # including a policy-generated request. A reporter reply cannot revive it.
    resets = [
        latest_event(timeline, label)
        for label in ("needs-triage", "triage/needs-information")
    ]
    return not any(
        reset and event_order(reset) > event_order(event) for reset in resets
    )

def human_only_waived(timeline, facts):
    """A trusted Labels-picker removal outranks the intake body preference until re-added."""
    removal = latest_event([e for e in timeline if trusted_event(e, facts)], "human-only", "unlabeled")
    added = latest_event(timeline, "human-only")
    return bool(removal) and (not added or event_order(removal) > event_order(added))



def delivery_evidence(body, catalog):
    text = headings(body).get("delivery evidence", "")
    patterns = {
        "revision": r"^Fix revision:\s*([0-9a-f]{40})\s*$",
        "url": r"^Release/build:\s*(https://\S+)\s*$",
        "verify": r"^Verify:\s*(\S.*)$",
    }
    if catalog["delivery"]["type"] == "image":
        patterns["image"] = r"^Image:\s*(\S+@sha256:[0-9a-f]{64})\s*$"
    else:
        patterns.update({"package": r"^Package:\s*(\S.*)$", "version": r"^Version:\s*(\S.*)$"})
    matches = {key: re.search(pattern, text, re.M | re.I) for key, pattern in patterns.items()}
    if not all(matches.values()):
        return None
    evidence = {key: match[1].strip() for key, match in matches.items()}
    if any(value.lower() in EMPTY for value in evidence.values()):
        return None
    return evidence


def referenced_issues(body, repository):
    # Full repository qualifiers must match; never interpret another repo's #N locally.
    expression = r"\b(?:refs?|references|close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:(https://github\.com/[^\s]+/issues/)|(\w[\w.-]*/[\w.-]+))?#?(\d+)\b"
    numbers = set()
    for match in re.finditer(expression, body or "", re.I):
        url, repo, number = match.groups()
        if url and url != f"https://github.com/{repository}/issues/":
            continue
        if repo and repo != repository:
            continue
        numbers.add(int(number))
    return numbers


def _intake_labels(record, catalog):
    """Apply caller-owned literal metadata rules; never grant consent or scope."""
    title = (record.get("title") or "")[:512].strip().lower()
    body = (record.get("body") or "")[:65536].lower()
    fields = headings(body)
    wanted = set()
    for rule in catalog.get("intake_rules", []):
        selectors = rule["match"]
        matches = (
            ("title_prefixes" not in selectors or any(title.startswith(value.lower()) for value in selectors["title_prefixes"]))
            and ("body_contains" not in selectors or any(value.lower() in body for value in selectors["body_contains"]))
            and ("body_headings" not in selectors or any(value.lower() in fields for value in selectors["body_headings"]))
        )
        if matches:
            wanted.update(rule["labels"])
    return wanted


def plan(record, facts, catalog, *, migrate=False, labels_only=False):
    """Return a proposed public label/comment/state transition without performing I/O."""
    validate_catalog(catalog)
    quiet = migrate or labels_only
    original = labels_of(record)
    aliases = catalog["label_aliases"] if migrate else {}
    alias_remove = original & set(aliases)
    alias_add = {aliases[name] for name in alias_remove if aliases[name] is not None}
    current = (original - alias_remove) | alias_add
    unmanaged = protected_labels(catalog)
    classification = {name for name in current if name.lower() not in unmanaged}
    intake = set()
    if record.get("state") != "closed" and "pull_request" not in record:
        intake = _intake_labels(record, catalog)
        if any(name.startswith("kind/") for name in classification):
            intake = {name for name in intake if not name.startswith("kind/")}
        current.update(intake)
        classification.update(intake)
    marker = catalog["comment_marker"]
    stages, retired = set(catalog["stages"]), set(catalog["retired_stages"])
    if record.get("state") == "closed" or "pull_request" in record:
        if not any(name.startswith("kind/") and name in catalog["labels"] for name in classification):
            source_kinds = {target for name, target in catalog.get("kind_sources", {}).items() if name in current}
            if len(source_kinds) == 1:
                alias_add.update(source_kinds)
                current.update(source_kinds)
        remove = current & (stages | retired) if "pull_request" in record else current & retired
        rendered = status_report(record, facts, catalog, {"stage": None, "close": False}) if "pull_request" in record and record.get("state") != "closed" and not quiet else {}
        return {
            "number": record["number"],
            "add": sorted(alias_add - original - remove),
            "remove": sorted((remove | alias_remove) & original),
            "comment": rendered.get("comment"),
            "notify_reporter": False,
            "notification_action": None,
            "request_id": None,
            "close": False,
            "stage": None,
        }

    body = record.get("body") or ""
    fields = headings(body)
    preference = fields.get("automation preference", "").strip()
    requested = (
        preference == "Human interaction only"
        or bool(re.search(r"<!--\s*automation-preference:\s*human-only\s*-->", body))
    )
    if not preference or preference.lower() in EMPTY:
        requested |= bool(
            re.search(r"<!--\s*[\w-]*queue-preference:\s*3-human-queue\s*-->", body)
        )
    # The body seeds the preference at intake; afterwards the label is the control.
    human_only = (
        "human-only" in current
        or "3-human-queue" in current
        or (requested and not human_only_waived(facts.get("timeline", []), facts))
    )
    if migrate and "needs-human" in current and not (current & stages):
        human_only = True
    tracking = record["number"] in catalog["standing_issues"] or bool(
        current & {"tracking", "Epic", "epic", "kind/epic"}
    )
    kind = {label for label in classification if label.startswith("kind/")}
    kind_ambiguous = len(kind) > 1 or bool(kind - set(catalog["labels"]))
    if kind_ambiguous:
        choices = [authorized_stage_event(facts.get("timeline", []), facts, name)
                   for name in kind if name in catalog["labels"]]
        choice = max((e for e in choices if e), key=event_order, default=None)
        unknown_events = [latest_event(facts.get("timeline", []), name)
                          for name in kind - set(catalog["labels"])]
        if choice and all(e and event_order(choice) > event_order(e) for e in unknown_events):
            kind = {choice["label"]["name"]}
            kind_ambiguous = False
    if not kind and not kind_ambiguous:
        source_kinds = {target for name, target in catalog.get("kind_sources", {}).items() if name in current}
        if len(source_kinds) == 1:
            kind = source_kinds
        elif source_kinds:
            kind_ambiguous = True
    if not kind and not kind_ambiguous:
        if (
            "bug" in current
            or "what happened?" in fields
            or re.search(
                r"<!--\s*report-type:\s*bug\s*-->|^## .*\bBug Report\b",
                body,
                re.M | re.I,
            )
        ):
            kind = {"kind/bug"}
        elif "problem to solve" in fields or re.search(
            r"<!--\s*report-type:\s*feature\s*-->|^## .*\bFeature Request\b",
            body,
            re.M | re.I,
        ):
            kind = {"kind/feature"}
        elif tracking:
            kind = {"kind/task"}
    timeline = facts.get("timeline", [])
    approved = approved_scope(timeline, facts)
    found = current & stages
    human_events = [authorized_stage_event(timeline, facts, label) for label in stages]
    decision = max((e for e in human_events if e), key=event_order, default=None)
    requested = decision["label"]["name"] if decision else None
    stage = "needs-triage"
    if (
        requested == "triage/needs-information"
        or found == {"triage/needs-information"}
        or ("needs-decision" in current and not approved)
    ):
        stage = "triage/needs-information"
    # A decision request on accepted work pauses it (needs-human stays on) but
    # keeps acceptance, so resolving the decision resumes without re-accepting.
    if approved and not tracking:
        stage = "triage/accepted"
    evidence = delivery_evidence(body, catalog)
    if (
        requested in {"awaiting-release", "needs-verification"}
        and "last_edited_at" in facts
    ):
        recent = (
            not facts["last_edited_at"]
            or decision["created_at"] > facts["last_edited_at"]
        )
        if recent:
            stage = (
                requested
                if requested != "needs-verification" or evidence
                else "awaiting-release"
            )

    info_event = authorized_stage_event(timeline, facts, "triage/needs-information")
    if not info_event:
        info_event = latest_event([e for e in timeline if lifecycle_bot(e.get("actor") or {})], "triage/needs-information")
    comments = facts.get("comments", [])
    actor = record.get("user", {}).get("login")
    requester = "maintainer" if "needs-decision" in current or tracking or record.get("user", {}).get("type") != "User" else "reporter"
    replies = [
        c
        for c in comments
        if c.get("user", {}).get("type") == "User"
        and c.get("user", {}).get("login") == actor
        and (
            not info_event or c.get("created_at", "") > info_event.get("created_at", "")
        )
        and marker not in (c.get("body") or "")
    ]
    edited_answer = (
        info_event
        and facts.get("last_edited_at")
        and facts["last_edited_at"] > info_event["created_at"]
    )
    answered = bool(
        requester == "reporter" and info_event and (replies or edited_answer)
    )
    if stage == "triage/needs-information" and answered:
        stage = "needs-triage"

    missing = []
    if "what happened?" in fields:
        for name in catalog.get("bug_fields", []):
            if fields.get(name.lower(), "").lower() in EMPTY:
                missing.append(name)
    elif "problem to solve" in fields:
        for name in catalog.get("feature_fields", []):
            if fields.get(name.lower(), "").lower() in EMPTY:
                missing.append(name)
    if (
        missing
        and stage in {"needs-triage", "triage/accepted"}
        and not tracking
        and not answered
    ):
        stage = "triage/needs-information"

    desired = {stage} | kind
    if not kind or kind_ambiguous:
        desired.add("needs-kind")
    if tracking:
        desired.add("tracking")
    if human_only:
        desired.add("human-only")
    active_gate_labels = sorted(current & set(catalog.get("gate_labels", [])))
    gated = (
        stage != "triage/accepted"
        or not kind
        or kind_ambiguous
        or human_only
        or tracking
        or bool(current & {"blocked", "hold", "needs-decision"})
        or bool(active_gate_labels)
    )
    if gated:
        desired.add("needs-human")
    managed = stages | retired | {"needs-kind", "needs-human"} | {label for label in classification if label.startswith("kind/")}
    # Never clear an independent human/app routing gate just because scope was
    # accepted. Only the lifecycle bot's own automatic gate is removable.
    gate_event = latest_event(timeline, "needs-human")
    gate_actor = (gate_event or {}).get("actor") or {}
    automatic_gate = (
        gate_actor.get("type") == "Bot"
        and gate_actor.get("login") == "github-actions[bot]"
    )
    if "needs-human" in current and not automatic_gate:
        desired.add("needs-human")

    close = False
    if stage == "needs-verification":
        verify_event = authorized_stage_event(timeline, facts, "needs-verification")
        responses = [
            c
            for c in replies
            if re.match(
                r"^\s*(?:confirmed fixed|still broken)\b", c.get("body") or "", re.I
            )
            and verify_event
            and c["created_at"] > verify_event["created_at"]
        ]
        response = max(
            responses, key=lambda c: (c["created_at"], c.get("id", 0)), default=None
        )
        if response and re.match(r"^\s*still broken\b", response["body"], re.I):
            desired.difference_update(stages)
            desired.update({"needs-triage", "needs-human"})
            stage = "needs-triage"
        elif response:
            close = True

    request_event = authorized_stage_event(timeline, facts, "needs-verification") if stage == "needs-verification" else info_event
    # Automatic missing-field requests retain one semantic anchor across bot restorations.
    request_id = request_identity(request_event, record)
    if stage == "triage/needs-information" and (not request_event or lifecycle_bot(request_event.get("actor") or {})):
        request_id = f"initial:{record['number']}"
    context = {
        "stage": stage, "approved": approved, "tracking": tracking,
        "human_only": human_only, "automatic_gate": automatic_gate,
        "missing": missing, "requester": requester, "delivery_evidence": evidence,
        "close": close, "request_event": request_event, "request_id": request_id,
        "kind_ambiguous": kind_ambiguous, "kind": kind,
        "active_gate_labels": active_gate_labels,
    }
    rendered = status_report(record, facts, catalog, context)
    return {
        "number": record["number"],
        "add": sorted((desired | {name for name in alias_add | intake if not name.startswith("kind/")}) - original),
        "remove": sorted(((current & managed) - desired | alias_remove) & original),
        "comment": None if quiet else rendered["comment"],
        "notify_reporter": False if quiet else rendered["notify_reporter"],
        "notification_action": None if quiet else rendered["notification_action"],
        "request_id": request_id,
        "close": False if quiet else close,
        "stage": stage,
    }


class GitHub:
    def __init__(self, repo, catalog):
        validate_catalog(catalog, repo)
        self.repo = repo
        self.catalog = catalog
        self.permission_cache = {}
        self.pr_cache = {}
        self.writes_authorized = False

    def request(self, method, path, body=None, *, pages=False):
        if path == "graphql":
            query = (body or {}).get("query", "")
            if not re.match(r"^\s*query\b", query) or re.search(r"\bmutation\b", query):
                raise ValueError("GraphQL mutations are not part of this issue policy")
        elif method != "GET":
            parsed = urlsplit(path)
            segments = unquote(parsed.path).split("/")
            if parsed.scheme or parsed.netloc or parsed.fragment or parsed.query or segments[:3] != ["repos", *self.repo.split("/")] or any(part in {".", "..", ""} for part in segments):
                raise ValueError(f"Write outside {self.repo} refused")
            if not self.writes_authorized:
                raise RuntimeError("Writes require reviewed default-branch policy and trusted action source")
        command = ["gh", "api", "--method", method, path]
        if pages:
            command += ["--paginate", "--slurp"]
        if body is not None:
            command += ["--input", "-"]
        result = subprocess.run(
            command,
            input=json.dumps(body) if body is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"GitHub {method} {path} failed: {result.stderr.strip()}"
            )
        if not result.stdout.strip():
            return None
        value = json.loads(result.stdout)
        return [item for page in value for item in page] if pages else value

    def permission(self, login):
        if login not in self.permission_cache:
            data = self.request(
                "GET",
                f"repos/{self.repo}/collaborators/{quote(login, safe='')}/permission",
            )
            self.permission_cache[login] = data.get("permission", "none")
        return self.permission_cache[login]

    def collect(self, number, *, record=None, quiet=False):
        root = f"repos/{self.repo}/issues/{number}"
        record = record if record is not None else self.request("GET", root)
        if not record.get("html_url", "").startswith(
            f"https://github.com/{self.repo}/"
        ):
            raise ValueError("Issue transferred outside configured repository; no writes permitted")
        if record.get("number") != number:
            raise ValueError("Collected record number differs from the requested target")
        if quiet and (record.get("state") == "closed" or "pull_request" in record):
            # Quiet historical/PR plans use only state/labels; never invent grants.
            # Preserve every list record and re-read freshness before any apply.
            return record, {"comments": [], "timeline": [], "permissions": {}, "linked_prs": []}
        comments = self.request("GET", root + "/comments?per_page=100", pages=True)
        timeline = self.request("GET", root + "/timeline?per_page=100", pages=True)
        facts = {
            "comments": comments,
            "timeline": timeline,
            "permissions": {},
            "linked_prs": [],
        }
        actors = {
            e["actor"]["login"]
            for e in timeline
            if (e.get("actor") or {}).get("type") == "User"
            and e.get("event") in {"labeled", "unlabeled"}
        }
        actors |= {
            c["user"]["login"]
            for c in comments
            if c.get("user", {}).get("type") == "User"
        }
        facts["permissions"] = {login: self.permission(login) for login in actors}
        owner, name = self.repo.split("/")
        variables = {"owner": owner, "name": name, "number": number}
        if "pull_request" in record:
            facts["pull_request"] = self.request(
                "GET", f"repos/{self.repo}/pulls/{number}"
            )
            query = 'query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewDecision mergeable}}}'
            native = self.request(
                "POST", "graphql", {"query": query, "variables": variables}
            )
            if native.get("errors"):
                raise RuntimeError(
                    "Cannot read native PR state: " + json.dumps(native["errors"])
                )
            native = native["data"]["repository"]["pullRequest"]
            facts["pull_request"].update(
                {
                    "review_decision": native["reviewDecision"],
                    "native_mergeable": native["mergeable"],
                }
            )
            return record, facts
        query = 'query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){issue(number:$number){lastEditedAt}}}'
        result = self.request(
            "POST", "graphql", {"query": query, "variables": variables}
        )
        if result.get("errors"):
            raise RuntimeError(
                "Cannot verify issue edit history: " + json.dumps(result["errors"])
            )
        facts["last_edited_at"] = result["data"]["repository"]["issue"]["lastEditedAt"]
        for event in timeline:
            source = (event.get("source") or {}).get("issue") or {}
            url = source.get("html_url", "")
            if "pull_request" not in source or not url.startswith(
                f"https://github.com/{self.repo}/pull/"
            ):
                continue
            pr_number = source["number"]
            if pr_number not in self.pr_cache:
                self.pr_cache[pr_number] = self.request(
                    "GET", f"repos/{self.repo}/pulls/{pr_number}"
                )
            pr = self.pr_cache[pr_number]
            if number in referenced_issues(pr.get("body"), self.repo):
                facts["linked_prs"].append(pr)
        return record, facts

    def require_main_ci(self, repo, branch, sha, workflows, deadline=None):
        """Missing, pending, skipped, and failed main runs are not deployment evidence.

        A run still in progress is polled until ``deadline`` (a ``time.monotonic()``
        value); if it is still running then, MainCIPending is raised instead of the
        generic failure so callers can defer rather than report a broken deployment.
        """
        if not workflows:
            raise RuntimeError("Apply requires repository-owned main_ci_workflows")
        for workflow in workflows:
            path = f"repos/{repo}/actions/workflows/{quote(workflow.rsplit('/', 1)[-1], safe='')}/runs?head_sha={sha}&branch={quote(branch, safe='')}&per_page=100"
            while True:
                runs = self.request("GET", path)["workflow_runs"]
                candidates = [run for run in runs if run.get("head_sha") == sha
                              and run.get("head_branch") == branch
                              and run.get("event") in {"push", "workflow_dispatch"}]
                latest = max(candidates, key=lambda run: (run["id"], run.get("run_attempt", 1)), default=None)
                if latest and latest.get("status") == "completed" and latest.get("conclusion") == "success":
                    break
                if latest and latest.get("status") != "completed":
                    remaining = (deadline - time.monotonic()) if deadline is not None else 0
                    if remaining > 0:
                        time.sleep(min(MAIN_CI_POLL_SECONDS, remaining))
                        continue
                    raise MainCIPending(f"Main CI still running: {repo} {workflow} at {sha}")
                raise RuntimeError(f"Apply requires successful main CI: {repo} {workflow} at {sha}")

    def require_deployed_policy(self, catalog_path, workspace, main_ci_wait=0):
        """Refuse feature policies, fork code, mutable action substitutions and local credentials."""
        if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != self.repo:
            raise RuntimeError("Apply requires the configured repository's GitHub Actions workflow")
        action_ref = os.environ.get("ISSUE_POLICY_ACTION_REF", "")
        if os.environ.get("ISSUE_POLICY_ACTION_REPOSITORY") != ACTION_REPOSITORY or (
            action_ref != ACTION_REF and not re.fullmatch(r"[0-9a-f]{40}", action_ref)
        ):
            raise RuntimeError("Apply requires the released first-party issue-lifecycle action @v1")
        if not os.environ.get("GH_TOKEN") or os.environ.get("GH_TOKEN") != os.environ.get("ISSUE_POLICY_WORKFLOW_TOKEN"):
            raise RuntimeError("Apply requires the workflow GITHUB_TOKEN; user tokens are refused")
        repository = self.request("GET", f"repos/{self.repo}")
        branch = repository["default_branch"]
        workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
        prefix, suffix = f"{self.repo}/", f"@refs/heads/{branch}"
        if not workflow_ref.startswith(prefix) or not workflow_ref.endswith(suffix):
            raise RuntimeError("Apply requires the caller workflow on its default branch")
        workflow = workflow_ref[len(prefix):-len(suffix)]
        if not re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", workflow):
            raise RuntimeError("Invalid caller workflow path")
        workspace = Path(workspace).resolve()
        catalog_path = Path(catalog_path).resolve()
        try:
            relative = catalog_path.relative_to(workspace).as_posix()
        except ValueError as error:
            raise RuntimeError("Catalog must come from the trusted caller checkout") from error
        if not relative.startswith(".github/"):
            raise RuntimeError("Caller catalog must live under .github")
        default_sha = self.request("GET", f"repos/{self.repo}/commits/{quote(branch, safe='')}")["sha"]
        workflow_sha = os.environ.get("GITHUB_WORKFLOW_SHA", "")
        if not re.fullmatch(r"[0-9a-f]{40}", workflow_sha):
            raise RuntimeError("Caller workflow revision is unavailable")
        comparison = self.request("GET", f"repos/{self.repo}/compare/{workflow_sha}...{default_sha}")
        if comparison.get("status") not in {"ahead", "identical"}:
            raise RuntimeError("Caller workflow revision is not merged on the default branch")
        def contents(repo, path, ref):
            data = self.request("GET", f"repos/{repo}/contents/{path}?ref={quote(ref, safe='')}")
            if data.get("encoding") != "base64" or not isinstance(data.get("content"), str):
                raise RuntimeError("Cannot verify trusted policy source bytes")
            return base64.b64decode(data["content"], validate=False)
        if contents(self.repo, relative, default_sha) != catalog_path.read_bytes():
            raise RuntimeError("Apply requires the reviewed catalog deployed on the default branch")
        if contents(self.repo, workflow, default_sha) != contents(self.repo, workflow, workflow_sha):
            raise RuntimeError("Caller workflow changed; start a new default-branch run")
        if contents(self.repo, workflow, default_sha) != (workspace / workflow).read_bytes():
            raise RuntimeError("Caller checkout must contain the reviewed default-branch workflow")
        action_repo = self.request("GET", f"repos/{ACTION_REPOSITORY}")
        action_default = action_repo["default_branch"]
        released_sha = self.request("GET", f"repos/{ACTION_REPOSITORY}/commits/{ACTION_REF}")["sha"]
        # $/ composition may report the running commit rather than its tag name.
        # That commit must be exactly the managed release, never a candidate SHA.
        if action_ref not in {ACTION_REF, released_sha}:
            raise RuntimeError("Running action commit is not the managed v1 release")
        action_head = self.request("GET", f"repos/{ACTION_REPOSITORY}/commits/{quote(action_default, safe='')}")["sha"]
        comparison = self.request("GET", f"repos/{ACTION_REPOSITORY}/compare/{released_sha}...{action_head}")
        if comparison.get("status") not in {"ahead", "identical"}:
            raise RuntimeError("Released action revision is not merged on its default branch")
        source_root = Path(__file__).resolve().parents[1]
        for relative in SOURCE_FILES:
            if contents(ACTION_REPOSITORY, relative, released_sha) != (source_root / relative).read_bytes():
                raise RuntimeError("Running action differs from the reviewed released source")
        deadline = time.monotonic() + main_ci_wait
        self.require_main_ci(self.repo, branch, default_sha, self.catalog.get("main_ci_workflows", []), deadline)
        self.require_main_ci(ACTION_REPOSITORY, action_default, released_sha,
                             [".github/workflows/unit-tests.yml", ".github/workflows/actionlint.yml"], deadline)
        self.writes_authorized = True

    def sync_catalog(self, catalog, apply):
        current = {
            label["name"]: label
            for label in self.request(
                "GET", f"repos/{self.repo}/labels?per_page=100", pages=True
            )
        }
        for name, definition in (catalog["stages"] | catalog["labels"]).items():
            have = current.get(name)
            if have and all(
                have.get(key) == value for key, value in definition.items()
            ):
                continue
            print(
                json.dumps(
                    {"catalog": name, "operation": "update" if have else "create"}
                )
            )
            if apply:
                path = f"repos/{self.repo}/labels" + (
                    "/" + quote(name, safe="") if have else ""
                )
                self.request(
                    "PATCH" if have else "POST", path, {"name": name, **definition}
                )

    def apply(self, record, facts, result):
        marker = self.catalog["comment_marker"]
        # Re-read immediately before writing; abandon a stale plan rather than overwrite a human.
        fresh = self.request("GET", f"repos/{self.repo}/issues/{record['number']}")
        if (
            not fresh.get("html_url", "").startswith(
                f"https://github.com/{self.repo}/"
            )
            or fresh["updated_at"] != record["updated_at"]
            or labels_of(fresh) != labels_of(record)
            or fresh.get("body") != record.get("body")
        ):
            raise StaleRecord(
                f"#{record['number']} changed during reconciliation; no stale writes applied"
            )
        root = f"repos/{self.repo}/issues/{record['number']}"
        # Install negative gates before removing old labels; never clear unrelated namespaces.
        if result["add"]:
            self.request("POST", root + "/labels", {"labels": result["add"]})
        for label in result["remove"]:
            self.request("DELETE", root + "/labels/" + quote(label, safe=""))
        if result["comment"]:
            authorized = lambda c: (
                c.get("user", {}).get("type") == "Bot"
                and c.get("user", {}).get("login") == "github-actions[bot]"
            )
            markers = [marker, *self.catalog.get("prior_comment_markers", [])]
            machine_statuses = [
                c for c in facts["comments"] if authorized(c) and (
                    any((c.get("body") or "").startswith(known) for known in markers)
                    or re.match(
                        r"^This issue has been marked .+ as part of the factory issue pipeline\.",
                        (c.get("body") or "").strip(),
                    )
                )
            ]
            prior = [c for c in machine_statuses if (c.get("body") or "").startswith(marker)] or machine_statuses
            notification = None
            text = result["comment"]
            if result.get("notify_reporter") and result.get("notification_action") and record.get("user", {}).get("type") == "User":
                key = hashlib.sha256(json.dumps({
                    "repository": self.repo, "number": record["number"],
                    "request": result["request_id"], "action": result["notification_action"],
                }, sort_keys=True).encode()).hexdigest()
                notification = marker.removesuffix(" -->") + ":request:" + key + " -->"
                person = record["user"]["login"]
                text = text.replace(marker, marker + f"\n@{person}", 1) + "\n\n" + notification
            already_notified = notification and any(
                notification in (c.get("body") or "").splitlines() and authorized(c)
                for c in facts["comments"]
            )
            if prior:
                if notification and not already_notified:
                    # Updating the status is not a notification. A new targeted comment is.
                    notice = text.replace(
                        marker, self.catalog["display_name"] + " lifecycle action request", 1
                    )
                    self.request("POST", root + "/comments", {"body": notice})
                if prior[-1]["body"] != text:
                    self.request(
                        "PATCH",
                        f"repos/{self.repo}/issues/comments/{prior[-1]['id']}",
                        {"body": text},
                    )
                current_url = prior[-1].get("html_url") or f"https://github.com/{self.repo}/issues/{record['number']}#issuecomment-{prior[-1]['id']}"
                for superseded in machine_statuses:
                    if superseded["id"] == prior[-1]["id"]:
                        continue
                    archive = (
                        f"**Archived automated status:** Superseded by [the current lifecycle status]({current_url}).\n\n"
                        "<details>\n<summary>Previous automated report</summary>\n\n"
                        + superseded["body"] + "\n\n</details>"
                    )
                    self.request(
                        "PATCH", f"repos/{self.repo}/issues/comments/{superseded['id']}",
                        {"body": archive},
                    )
            else:
                self.request("POST", root + "/comments", {"body": text})
        if result["close"]:
            self.request(
                "PATCH", root, {"state": "closed", "state_reason": "completed"}
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="must match the caller catalog repository")
    parser.add_argument("--catalog", type=Path, default=Path(".github/issue-policy.json"))
    parser.add_argument("--workspace", type=Path, default=Path(os.environ.get("GITHUB_WORKSPACE", ".")))
    parser.add_argument("--backup-dir", type=Path, default=Path.home() / ".local/state/issue-policy")
    parser.add_argument("--issue", type=int, action="append")
    parser.add_argument("--event-file", type=Path)
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="read-only issue/facts fixture; never used for live writes",
    )
    parser.add_argument(
        "--output", type=Path, help="save the preview/snapshot for review"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--authorize-only", action="store_true", help="verify deployment without reading or changing issues")
    parser.add_argument(
        "--labels-only",
        action="store_true",
        help="repair labels without comments or closures",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="conservatively migrate existing human-queue/needs-human preferences",
    )
    parser.add_argument(
        "--retire-labels",
        action="store_true",
        help="remove retired definitions only after all assignments have been migrated",
    )
    parser.add_argument(
        "--confirm-client-cutover",
        action="store_true",
        help="acknowledge older report clients no longer need retired definitions",
    )
    args = parser.parse_args(argv)
    if args.apply and (args.dry_run or args.snapshot):
        parser.error("--apply cannot be combined with --dry-run or --snapshot")
    if args.retire_labels and args.apply and not args.confirm_client_cutover:
        parser.error(
            "retain inert definitions until report clients are updated; retirement requires --confirm-client-cutover"
        )
    if args.apply and os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error(
            "Apply through the merged caller workflow_dispatch; a local user token would give automatic gates human provenance"
        )
    if args.issue and any(number < 1 for number in args.issue):
        parser.error("Issue numbers must be positive")
    catalog_path = args.catalog if args.catalog.is_absolute() else args.workspace / args.catalog
    catalog = validate_catalog(json.loads(catalog_path.read_text()), args.repo)
    args.repo = catalog["repository"]
    github = GitHub(args.repo, catalog)
    if args.apply:
        # --authorize-only gates Prow writes on exit status, so it never waits or defers.
        try:
            github.require_deployed_policy(
                catalog_path, args.workspace,
                main_ci_wait=0 if args.authorize_only else MAIN_CI_WAIT_SECONDS,
            )
        except MainCIPending as error:
            if args.authorize_only:
                raise
            print(f"::notice::{error}; nothing applied, this event is deferred to the next reconciliation")
            return 0
    if args.authorize_only:
        if not args.apply:
            parser.error("--authorize-only requires --apply")
        return 0
    if args.snapshot:
        entries = json.loads(args.snapshot.read_text())
    else:
        numbers = args.issue
        listed_records = {}
        if args.event_file:
            event = json.loads(args.event_file.read_text())
            if event.get("repository", {}).get("full_name") != args.repo:
                parser.error("event repository is outside the configured repository")
            target = event.get("issue") or event.get("pull_request")
            numbers = [target["number"]] if target else None
            if event.get("pull_request"):
                numbers += sorted(referenced_issues(event["pull_request"].get("body"), args.repo))
        if numbers is None:
            listed = github.request(
                "GET",
                f"repos/{args.repo}/issues?state={'all' if args.migrate or args.retire_labels else 'open'}&per_page=100",
                pages=True,
            )
            listed_records = {record["number"]: record for record in listed}
            numbers = list(listed_records)
        entries = []
        for number in dict.fromkeys(numbers):
            record, facts = github.collect(number, record=listed_records.get(number),
                                          quiet=args.migrate or args.labels_only or args.retire_labels)
            entries.append({"record": record, "facts": facts})
    output = [
        {
            **entry,
            "plan": plan(
                entry["record"],
                entry["facts"],
                catalog,
                migrate=args.migrate,
                labels_only=args.labels_only or args.retire_labels,
            ),
        }
        for entry in entries
    ]
    legacy_changes = any(
        set(entry["plan"]["remove"]) & (set(catalog["retired_stages"]) | set(catalog["label_aliases"]))
        for entry in output
    )
    if args.apply and (args.migrate or args.retire_labels or legacy_changes):
        # Archive old assignments and definitions, including closed history, before any mutation.
        backup_dir = args.backup_dir / args.repo.replace("/", "-")
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"{stamp}-{uuid4().hex}.json"
        backup = {
            "repository": args.repo,
            "catalog": catalog,
            "issues": github.request(
                "GET", f"repos/{args.repo}/issues?state=all&per_page=100", pages=True
            ),
            "labels": github.request(
                "GET", f"repos/{args.repo}/labels?per_page=100", pages=True
            ),
            "preview": output,
        }
        backup_path.write_text(json.dumps(backup, indent=2) + "\n")
        print(f"Migration backup: {backup_path}")
    if not args.snapshot:
        github.sync_catalog(catalog, args.apply)
    skipped = []
    for entry in output:
        result = entry["plan"]
        print(
            json.dumps(
                {
                    "number": result["number"],
                    "stage": result["stage"],
                    "add": result["add"],
                    "remove": result["remove"],
                    "close": result["close"],
                }
            )
        )
        if args.apply and any(result[name] for name in ("add", "remove", "comment", "close")):
            try:
                github.apply(entry["record"], entry["facts"], result)
            except StaleRecord as error:
                skipped.append(result["number"])
                print(str(error), file=sys.stderr)
    if args.output:
        args.output.write_text(json.dumps(output, indent=2) + "\n")
    if skipped:
        raise RuntimeError(
            f"Skipped changed records {skipped}; review their current state and let the next reconciliation reassess them. Other records were processed; backup retained."
        )
    if args.retire_labels and args.apply:
        remaining = github.request(
            "GET", f"repos/{args.repo}/issues?state=all&per_page=100", pages=True
        )
        stale = [
            (i["number"], sorted(labels_of(i) & (set(catalog["retired_stages"]) | set(catalog["label_aliases"]))))
            for i in remaining
            if labels_of(i) & (set(catalog["retired_stages"]) | set(catalog["label_aliases"]))
        ]
        if stale:
            raise RuntimeError(
                "Retirement refused; numbered/obsolete assignments remain: "
                + json.dumps(stale)
            )
        definitions = {
            i["name"]
            for i in github.request(
                "GET", f"repos/{args.repo}/labels?per_page=100", pages=True
            )
        }
        for name in set(catalog["retired_stages"]) | set(catalog["label_aliases"]):
            if name in definitions:
                github.request(
                    "DELETE", f"repos/{args.repo}/labels/{quote(name, safe='')}"
                )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
