#!/usr/bin/env python3
"""Authorize a small Prow command surface, then report observed GitHub outcomes.

Label mutations belong exclusively to the pinned upstream action, not this module.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from scripts.issue_policy import protected_labels
from scripts.issue_status import prow_report

PROW_CONFIG = ".github/prow.yaml"


class ApiError(RuntimeError):
    """A GitHub read or report write could not be confirmed."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class GitHub:
    def __init__(self, repository, token, api_url="https://api.github.com"):
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")

    def request(self, path="", *, method="GET", data=None):
        # This client cannot address other repositories or arbitrary API endpoints.
        url = f"{self.api_url}/repos/{self.repository}"
        if path:
            url += "/" + path
        request = Request(
            url,
            data=None if data is None else json.dumps(data).encode(),
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                message = json.load(error).get("message", error.reason)
            except (ValueError, AttributeError):
                message = error.reason
            raise ApiError(f"GitHub {method} {path or 'repository'} returned {error.code}: {message}", error.code) from error
        except (URLError, ValueError, TimeoutError) as error:
            raise ApiError(f"GitHub {method} {path or 'repository'} could not be read: {error}") from error

    def file_json(self, path, ref):
        response = self.request(f"contents/{path}?ref={quote(ref, safe='')}")
        if response.get("encoding") != "base64" or not isinstance(response.get("content"), str):
            raise ValueError(f"{path} is not a readable GitHub file")
        return json.loads(base64.b64decode(response["content"]))

    def labels(self, path):
        names = set()
        page = 1
        while True:
            response = self.request(f"{path}?per_page=100&page={page}")
            names.update(label["name"] for label in response)
            if len(response) < 100:
                return names
            page += 1


def family_values(catalog, family):
    prefix = family + "/"
    unmanaged = protected_labels(catalog)
    return sorted(name[len(prefix):] for name in catalog["labels"] if name.startswith(prefix) and name.lower() not in unmanaged)


def expected_config(catalog):
    """Derive the complete supported upstream configuration from the caller catalog."""
    families = {}
    for family in ("kind", "area"):
        values = family_values(catalog, family)
        if values:
            families[family] = {"values": values, "exclusive": family == "kind"}
    return {
        "labels": families,
        "hold": {"label": "hold"},
        "tide": {"merge_on_events": False},
        "require_matching_label": [],
    }


def supported_commands(catalog):
    commands = ["/help — list commands"]
    for family in ("kind", "area"):
        values = family_values(catalog, family)
        if values:
            action = "set kind" if family == "kind" else "add area"
            commands.append(f"/{family} VALUE — {action} ({', '.join(values)})")
            if family == "area":
                commands.append("/remove-area VALUE — remove area")
    if "hold" in catalog["labels"]:
        commands.extend(["/hold — pause", "/hold cancel — resume"])
    return commands


def result(command, outcome, reason, catalog, *, next_steps=None):
    return {
        "command": command,
        "outcome": outcome,
        "changes": {"add": [], "remove": []},
        "reason": reason,
        "next_steps": next_steps or ["Post one command per comment."],
        "supported_commands": supported_commands(catalog),
    }


def command_request(body):
    """Conservatively identify requests; only an entire one-line comment can execute.

    Reject rather than translate Markdown/prose or aggregate upstream's many-command
    syntax: upstream sees the original, unmodified event and must execute that alone.
    """
    body = body or ""
    if not re.search(r"^\s*/[a-zA-Z][\w-]*(?:\s|$)", body, re.M):
        return None
    return body.strip()


def plan_command(command, catalog, current):
    normalized = command.lower()
    if normalized in {"/help", "/prow help"}:
        return result(command, "help", "Maintainer commands for issues. Help changes nothing.", catalog), None
    if "\n" in command or "\r" in command:
        return result(command, "invalid", "Post one command per comment, with nothing else. Nothing ran.", catalog), None
    words = normalized.split()
    base = words[0]
    if base in {"/kind", "/area", "/remove-area"}:
        family = "kind" if base == "/kind" else "area"
        values = family_values(catalog, family)
        if len(words) != 2 or words[1] not in {value.lower() for value in values}:
            return result(command, "invalid", f"{base} needs one value: {', '.join(values) or '(none)'}. Nothing ran.", catalog), None
        canonical = next(value for value in values if value.lower() == words[1])
        label = family + "/" + canonical
        wanted = set(current)
        if base == "/kind":
            unmanaged = protected_labels(catalog)
            protected_kinds = sorted(name for name in current if name.lower().startswith("kind/") and name.lower() in unmanaged)
            if protected_kinds:
                return result(
                    command, "denied",
                    f"/kind would remove protected labels: {', '.join(protected_kinds)}. Nothing ran.",
                    catalog,
                    next_steps=[
                        f"Use GitHub's Labels picker to select {label} and deselect only other managed primary kinds. Leave {', '.join(protected_kinds)} and independent labels as they are.",
                    ],
                ), None
            wanted = {name for name in wanted if not name.lower().startswith("kind/")}
            wanted.add(label)
        elif base == "/area":
            wanted.add(label)
        else:
            wanted = {name for name in wanted if name.lower() != label.lower()}
        return result(command, "applied", "", catalog), {"upstream_command": "/" + family, "expected": sorted(wanted), "required": [] if base == "/remove-area" else [label]}
    if normalized in {"/hold", "/hold cancel", "/unhold", "/remove-hold"} and "hold" in catalog["labels"]:
        cancel = normalized != "/hold"
        wanted = {name for name in current if name.lower() != "hold"}
        if not cancel:
            wanted.add("hold")
        return result(command, "applied", "", catalog), {"upstream_command": "/hold", "expected": sorted(wanted), "required": [] if cancel else ["hold"]}
    return result(command, "invalid", "Command not available. Prow can only set kind/area or pause issues. Nothing ran.", catalog), None


def validate_config(catalog, config):
    expected = expected_config(catalog)
    # Values are a set, but no extra configuration/plugin authority is permitted.
    candidate = json.loads(json.dumps(config))
    for section in candidate.get("labels", {}).values():
        if isinstance(section, dict) and isinstance(section.get("values"), list):
            section["values"] = sorted(section["values"])
    if json.dumps(candidate, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError("Default-branch .github/prow.yaml must exactly match the catalog-derived kind/area families, exclusive kind, literal hold, no required-label rules, and disabled event merging")
    protected = set(catalog["stages"]) | set(catalog.get("retired_stages", []))
    if any(name.lower().startswith(("kind/", "area/")) for name in protected):
        raise ValueError("Lifecycle/stage labels cannot overlap Prow's descriptive kind/area families")
    names = list(catalog["labels"])
    if len({name.lower() for name in names}) != len(names):
        raise ValueError("Catalog label names must be unique case-insensitively")
    for family in ("kind", "area"):
        if any(not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value) for value in family_values(catalog, family)):
            raise ValueError("Prow kind/area catalog values must be lower-case command tokens")


def prepare(event, catalog, github, *, catalog_path=".github/issue-policy.json"):
    """Read immutable event identity and live API authority before upstream writes."""
    command = command_request(event.get("comment", {}).get("body"))
    if command is None:
        return None
    state = {"number": event["issue"]["number"], "pull_request": "pull_request" in event["issue"], "execute": False, "result": result(command, "invalid", "", catalog)}
    if event.get("action") != "created":
        state["result"] = result(command, "invalid", "Edited comments don't run. Post a new command comment.", catalog)
        return state
    actor = event.get("comment", {}).get("user") or {}
    sender = event.get("sender") or {}
    if actor.get("type") != "User" or actor.get("login") != sender.get("login") or actor.get("id") != sender.get("id"):
        state["result"] = result(command, "denied", "Only the person who posted the comment can run it. Bot commands don't run.", catalog)
        return state
    try:
        live_comment = github.request(f"issues/comments/{event['comment']['id']}")
        if (live_comment.get("user", {}).get("id") != actor.get("id")
                or live_comment.get("body") != event["comment"].get("body")
                or live_comment.get("updated_at") != event["comment"].get("updated_at")):
            raise ValueError("Comment changed since it was posted; post a new command comment")
        state["result"], execution = plan_command(command, catalog, set())
        if state["result"]["outcome"] == "help":
            return state
        permission = github.request(f"collaborators/{quote(actor['login'], safe='')}/permission").get("permission")
        if permission not in {"write", "maintain", "admin"}:
            state["result"] = result(command, "denied", f"You need write, maintain, or admin access (you have {permission or 'unknown'}). Ask a maintainer.", catalog)
            return state
        issue = github.request(f"issues/{state['number']}")
        if "pull_request" in event["issue"] or "pull_request" in issue:
            state["pull_request"] = True
            state["result"] = result(command, "denied", "Prow label controls are issue-only. Use the PR's review and merge controls.", catalog)
            return state
        if issue.get("state") != "open":
            raise ValueError("Commands only work on open issues; reopen it first")
        if execution is None:
            return state
        repo = github.request()
        ref = github.request(f"branches/{quote(repo['default_branch'], safe='')}")["commit"]["sha"]
        remote_catalog = github.file_json(catalog_path, ref)
        if remote_catalog != catalog:
            raise ValueError("Catalog differs from the default branch; rerun from the default branch")
        config = github.file_json(PROW_CONFIG, ref)
        validate_config(catalog, config)
        state["before"] = sorted(github.labels(f"issues/{state['number']}/labels"))
        state["result"], execution = plan_command(command, catalog, set(state["before"]))
        if execution is None:
            return state
        definitions = {name.lower() for name in github.labels("labels")}
        missing = [label for label in execution["required"] if label.lower() not in definitions]
        if missing:
            raise ValueError(f"Label definitions are missing: {', '.join(missing)}. Add them, then retry")
        state.update(execution)
        state.update({"execute": True, "config": f"{catalog['repository']}:{PROW_CONFIG}@{ref}"})
    except (ApiError, ValueError, KeyError, TypeError) as error:
        state["result"] = result(command, "invalid", f"Preflight refused: {error}.", catalog)
    return state


def observed_result(state, catalog, after, upstream_outcome):
    """Exit status alone is not a result: compare actual labels with the plan."""
    report = state["result"]
    before = set(state["before"])
    after = set(after)
    report["changes"] = {"add": sorted(after - before), "remove": sorted(before - after)}
    matches = {name.lower() for name in after} == {name.lower() for name in state["expected"]}
    if upstream_outcome != "success" or not matches:
        report.update({
            "outcome": "invalid",
            "reason": f"Prow step {upstream_outcome}. Labels {'match' if matches else 'do not match'} the request; changes below are actual API observations.",
            "next_steps": ["Check the run and current labels before posting another command."],
        })
    else:
        command = report["command"].lower()
        next_step = "Labels updated. Acceptance and assignment did not change."
        if command == "/hold":
            next_step = "Explain why it's paused. Post `/hold cancel` to resume."
        elif command in {"/hold cancel", "/unhold", "/remove-hold"}:
            next_step = "Hold removed. Other independent gates (`blocked`, `needs-human`) stay."
        report.update({
            "outcome": "applied",
            "reason": "GitHub confirms the labels." if report["changes"]["add"] or report["changes"]["remove"] else "Labels were already present.",
            "next_steps": [next_step],
        })
    return report


def finish(state, catalog, github, upstream_outcome):
    if state["execute"]:
        try:
            state["result"] = observed_result(state, catalog, github.labels(f"issues/{state['number']}/labels"), upstream_outcome)
        except ApiError as error:
            state["result"].update({
                "outcome": "invalid", "changes_unknown": True,
                "reason": f"Prow step {upstream_outcome}; could not read labels afterward: {error}. Changes unknown.",
                "next_steps": ["Check the run and current labels before retrying."],
            })
    if state.get("pull_request"):
        state["result"]["pull_request"] = True
        state["result"]["next_steps"] = [
            "Use the PR's normal review and merge controls; Prow doesn't change PRs."
        ]
    comment = prow_report(catalog, state["result"])
    response = github.request(f"issues/{state['number']}/comments", method="POST", data={"body": comment})
    if not response.get("id") or response.get("body") != comment:
        raise ApiError("GitHub did not confirm the Prow result comment")
    return state["result"]


def emit_outputs(**values):
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in values.items():
            text = str(value)
            if "\n" in text or "\r" in text:
                raise ValueError("Prow action outputs must be single-line values")
            output.write(f"{key}={text}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "report"])
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--catalog-path", default=".github/issue-policy.json")
    parser.add_argument("--state")
    parser.add_argument("--upstream-outcome", default="skipped")
    args = parser.parse_args(argv)
    catalog = json.loads(Path(args.catalog).read_text())
    repository = catalog["repository"]
    if os.environ.get("GITHUB_ACTIONS") != "true" or repository != os.environ.get("GITHUB_REPOSITORY"):
        raise ValueError("Prow writes require GitHub Actions and a catalog scoped to GITHUB_REPOSITORY")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or repository.lower().startswith("ublue-os/"):
        raise ValueError("Unsupported repository scope")
    github = GitHub(repository, os.environ["GH_TOKEN"], os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    if args.operation == "prepare":
        if os.environ.get("GITHUB_EVENT_NAME") != "issue_comment":
            emit_outputs(execute="false", state="")
            return 0
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        if event.get("repository", {}).get("full_name") != repository:
            raise ValueError("Immutable event repository differs from the caller catalog")
        state = prepare(event, catalog, github, catalog_path=args.catalog_path)
        if state is None:
            emit_outputs(execute="false", state="")
            return 0
        path = Path(os.environ["RUNNER_TEMP"]) / f"prow-command-{uuid4().hex}.json"
        path.write_text(json.dumps(state))
        emit_outputs(execute=str(state["execute"]).lower(), state=path, config=state.get("config", ""), command=state.get("upstream_command", ""))
        return 0
    state = json.loads(Path(args.state).read_text())
    report = finish(state, catalog, github, args.upstream_outcome)
    emit_outputs(outcome=report["outcome"])
    return int(state["execute"] and report["outcome"] != "applied")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ApiError, ValueError, KeyError, OSError) as error:
        print(f"Prow could not complete or publish its result: {error}", file=sys.stderr)
        sys.exit(1)
