"""Prow authorization and observed outcomes; upstream owns all label execution."""
import base64
from copy import deepcopy
import json

import pytest

from scripts import prow_commands as prow


@pytest.fixture
def catalog():
    return {
        "repository": "projectbluefin/example",
        "display_name": "Example",
        "comment_marker": "<!-- example-issue-lifecycle:v1 -->",
        "stages": {"needs-triage": {}, "triage/accepted": {}},
        "labels": {name: {} for name in [
            "kind/bug", "kind/feature", "kind/task", "kind/debt", "area/api", "area/docs",
            "hold", "needs-human", "human-only", "blocked",
        ]},
        "retired_stages": ["3-clanker-queue"],
        "protected_labels": ["kind/tech-debt", "source:agent"],
    }


@pytest.fixture
def event():
    actor = {"id": 7, "login": "maintainer", "type": "User"}
    return {
        "action": "created",
        "repository": {"full_name": "projectbluefin/example"},
        "issue": {"number": 12},
        "comment": {"id": 23, "body": "/kind feature", "updated_at": "2026-09-24T00:00:00Z", "user": actor},
        "sender": deepcopy(actor),
    }


class FixtureGitHub:
    """Read fixture for wrapper tests, never an imitation Prow implementation."""

    def __init__(self, catalog, event):
        self.catalog = catalog
        self.event = event
        self.permission = "write"
        self.issue = {"number": 12, "state": "open"}
        self.current = {"kind/bug", "needs-triage", "needs-human", "human-only", "blocked", "hold", "agent/owned", "hive/ready", "do-not-merge/security"}
        self.definitions = set(catalog["labels"])
        self.config = prow.expected_config(catalog)
        self.calls = []
        self.error_path = None
        self.comment_response = True

    def request(self, path="", *, method="GET", data=None):
        self.calls.append((method, path, data))
        if path == self.error_path:
            raise prow.ApiError("GitHub unavailable", 503)
        if method == "POST":
            assert path == "issues/12/comments"
            return {"id": 99, "body": data["body"]} if self.comment_response else {}
        if path == "issues/comments/23":
            return deepcopy(self.event["comment"])
        if path == "collaborators/maintainer/permission":
            return {"permission": self.permission}
        if path == "issues/12":
            return self.issue
        if path == "":
            return {"default_branch": "main"}
        if path == "branches/main":
            return {"commit": {"sha": "a" * 40}}
        raise AssertionError(f"Unexpected API call {method} {path}")

    def file_json(self, path, ref):
        assert ref == "a" * 40
        return self.catalog if path == ".github/issue-policy.json" else self.config

    def labels(self, path):
        if path == self.error_path:
            raise prow.ApiError("GitHub label observation unavailable", 503)
        return self.definitions if path == "labels" else self.current


def test_authorized_kind_replaces_exactly_one_without_gate_changes(catalog, event):
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    assert state["execute"]
    assert state["upstream_command"] == "/kind"
    assert set(state["expected"]) == (api.current - {"kind/bug"}) | {"kind/feature"}
    assert state["config"].endswith("@" + "a" * 40)
    assert all(method == "GET" for method, _, _ in api.calls)


@pytest.mark.parametrize("permission", ["read", "triage", "none", None])
def test_current_nonwriter_cannot_mutate_despite_maintainer_prose(catalog, event, permission):
    api = FixtureGitHub(catalog, event)
    api.permission = permission
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert state["result"]["outcome"] == "denied"
    assert state["result"]["changes"] == {"add": [], "remove": []}
    assert "write, maintain, or admin" in state["result"]["reason"]
    assert all(method == "GET" for method, _, _ in api.calls)


@pytest.mark.parametrize("permission", ["write", "maintain", "admin"])
def test_each_current_maintainer_permission_authorizes(catalog, event, permission):
    api = FixtureGitHub(catalog, event)
    api.permission = permission
    assert prow.prepare(event, catalog, api)["execute"]


@pytest.mark.parametrize("change", ["bot", "sender", "comment-id"])
def test_bot_or_mismatched_actor_cannot_mutate(catalog, event, change):
    if change == "bot":
        event["comment"]["user"]["type"] = "Bot"
    elif change == "sender":
        event["sender"]["login"] = "outsider"
    else:
        event["sender"]["id"] = 999
    api = FixtureGitHub(catalog, event)
    assert prow.prepare(event, catalog, api)["result"]["outcome"] == "denied"
    assert api.calls == []


def test_permission_api_failure_refuses_execution(catalog, event):
    api = FixtureGitHub(catalog, event)
    api.error_path = "collaborators/maintainer/permission"
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert "Preflight refused" in state["result"]["reason"]


def test_changed_comment_cannot_replay_event(catalog, event):
    api = FixtureGitHub(catalog, deepcopy(event))
    api.event["comment"]["body"] = "/kind bug"
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert "changed since" in state["result"]["reason"]


@pytest.mark.parametrize("command", [
    "/kind bug feature", "/kind made-up", "/kind", "/kind bug\n/kind feature",
    "/kind bug\n/hold cancel", "/kind bug\nThanks", "```\n/kind bug\n```",
    "/remove-kind bug", "/label triage/accepted", "/triage accepted", "/remove needs-human",
    "/approve", "/lgtm", "/assign", "/test all", "/check-required-labels",
    "/hold tomorrow", "/remove-area api docs", "/area secret", "/stage stable",
])
def test_invalid_scope_and_cardinality_never_execute(catalog, event, command):
    event["comment"]["body"] = command
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert state["result"]["outcome"] == "invalid"
    assert state["result"]["changes"] == {"add": [], "remove": []}
    assert all(method == "GET" for method, _, _ in api.calls)


@pytest.mark.parametrize("command", ["/help", "/prow help"])
def test_help_is_informational_not_upstream_help_label(catalog, event, command):
    event["comment"]["body"] = command
    api = FixtureGitHub(catalog, event)
    api.permission = "read"
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert state["result"]["outcome"] == "help"
    assert not any(path.startswith("collaborators/") for _, path, _ in api.calls)
    assert "help wanted" not in json.dumps(state["result"]["changes"])


@pytest.mark.parametrize("payload_pr", [True, False])
def test_pull_request_never_reaches_upstream_even_for_maintainer(catalog, event, payload_pr):
    api = FixtureGitHub(catalog, event)
    (event["issue"] if payload_pr else api.issue)["pull_request"] = {"url": "https://api.github.com/example"}
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert state["result"]["outcome"] == "denied"
    assert "issue-only" in state["result"]["reason"]


@pytest.mark.parametrize("command", ["/hold cancel", "/unhold", "/remove-hold"])
def test_hold_cancel_withdraws_only_literal_hold(catalog, event, command):
    event["comment"]["body"] = command
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    assert state["execute"]
    assert state["upstream_command"] == "/hold"
    assert set(state["expected"]) == api.current - {"hold"}
    report = prow.observed_result(state, catalog, set(state["expected"]), "success")
    assert report["changes"] == {"add": [], "remove": ["hold"]}
    assert report["outcome"] == "applied"
    assert "independent gates" in " ".join(report["next_steps"])


def test_hold_add_preserves_independent_pause_gates(catalog, event):
    event["comment"]["body"] = "/hold"
    api = FixtureGitHub(catalog, event)
    api.current.discard("hold")
    state = prow.prepare(event, catalog, api)
    assert set(state["expected"]) == api.current | {"hold"}


@pytest.mark.parametrize("command", ["/area docs", "/remove-area api"])
def test_area_operations_preserve_kind_stage_and_unrelated_labels(catalog, event, command):
    event["comment"]["body"] = command
    api = FixtureGitHub(catalog, event)
    api.current.add("area/api")
    state = prow.prepare(event, catalog, api)
    expected = api.current | {"area/docs"} if command == "/area docs" else api.current - {"area/api"}
    assert set(state["expected"]) == expected


def test_missing_label_definition_refuses_before_upstream_kind_removal(catalog, event):
    api = FixtureGitHub(catalog, event)
    api.definitions.remove("kind/feature")
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert "definitions are missing" in state["result"]["reason"]
    assert "kind/bug" in api.current


@pytest.mark.parametrize("bad_config", [
    {"hold": {"label": "needs-human"}},
    {"tide": {"merge_on_events": True}},
    {"require_matching_label": [{"regexp": ".*", "missing_label": "triage/accepted"}]},
    {"labels": {"kind": {"values": ["bug", "feature", "task"], "exclusive": False}}},
])
def test_unsafe_or_stale_config_refuses_all_execution(catalog, event, bad_config):
    api = FixtureGitHub(catalog, event)
    api.config.update(bad_config)
    assert not prow.prepare(event, catalog, api)["execute"]


def test_changed_default_catalog_refuses_execution(catalog, event):
    api = FixtureGitHub(deepcopy(catalog), event)
    api.catalog["labels"]["kind/new"] = {}
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert "differs from" in state["result"]["reason"]


def test_label_stage_family_overlap_is_not_a_descriptive_command(catalog):
    catalog["stages"]["kind/accepted"] = {}
    with pytest.raises(ValueError, match="overlap"):
        prow.validate_config(catalog, prow.expected_config(catalog))


def test_real_observation_reports_success_and_idempotency(catalog, event):
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    report = prow.observed_result(state, catalog, state["expected"], "success")
    assert report["outcome"] == "applied"
    assert report["changes"] == {"add": ["kind/feature"], "remove": ["kind/bug"]}
    api.current = set(state["expected"])
    state = prow.prepare(event, catalog, api)
    report = prow.observed_result(state, catalog, api.current, "success")
    assert report["changes"] == {"add": [], "remove": []}
    assert "already present" in report["reason"]


def test_upstream_failure_keeps_observed_partial_changes_not_fake_rollback(catalog, event):
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    report = prow.observed_result(state, catalog, api.current - {"kind/bug"}, "failure")
    assert report["outcome"] == "invalid"
    assert report["changes"] == {"add": [], "remove": ["kind/bug"]}
    assert "actual API observations" in report["reason"]


def test_success_exit_without_requested_transition_is_not_success(catalog, event):
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    report = prow.observed_result(state, catalog, api.current, "success")
    assert report["outcome"] == "invalid"
    assert "do not match" in report["reason"]


def test_observed_unexpected_gate_loss_is_not_reported_as_success(catalog, event):
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    report = prow.observed_result(state, catalog, set(state["expected"]) - {"needs-human"}, "success")
    assert report["outcome"] == "invalid"
    assert "needs-human" in report["changes"]["remove"]


def test_postread_failure_reports_unknown_mutation_and_uses_shared_renderer(catalog, event, monkeypatch):
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    api.error_path = "issues/12/labels"
    rendered = []
    monkeypatch.setattr(prow, "prow_report", lambda catalog, report: rendered.append(deepcopy(report)) or "Rendered result")
    report = prow.finish(state, catalog, api, "failure")
    assert report["changes_unknown"] is True
    assert report["outcome"] == "invalid"
    assert rendered == [report]
    assert api.calls[-1] == ("POST", "issues/12/comments", {"body": "Rendered result"})


@pytest.mark.parametrize("command,outcome", [("/help", "help"), ("/approve", "invalid"), ("/hold", "denied")])
def test_help_error_and_denial_all_use_shared_renderer(catalog, event, monkeypatch, command, outcome):
    event["comment"]["body"] = command
    api = FixtureGitHub(catalog, event)
    if outcome == "denied":
        api.permission = "read"
    state = prow.prepare(event, catalog, api)
    rendered = []
    monkeypatch.setattr(prow, "prow_report", lambda catalog, report: rendered.append(report["outcome"]) or "Report")
    report = prow.finish(state, catalog, api, "skipped")
    assert report["outcome"] == outcome
    assert rendered == [outcome]


def test_comment_write_must_be_confirmed(catalog, event):
    event["comment"]["body"] = "/help"
    api = FixtureGitHub(catalog, event)
    api.comment_response = False
    state = prow.prepare(event, catalog, api)
    with pytest.raises(prow.ApiError, match="did not confirm"):
        prow.finish(state, catalog, api, "skipped")


def test_normal_discussion_is_not_a_command(catalog, event):
    event["comment"]["body"] = "Please consider `/kind bug` after triage."
    assert prow.prepare(event, catalog, FixtureGitHub(catalog, event)) is None


def test_edited_event_does_not_execute(catalog, event):
    event["action"] = "edited"
    state = prow.prepare(event, catalog, FixtureGitHub(catalog, event))
    assert not state["execute"]
    assert "new command comment" in state["result"]["reason"]


def test_github_file_parser_reads_json_catalog_at_pinned_ref(monkeypatch):
    api = prow.GitHub("projectbluefin/example", "token")
    document = {"labels": {"kind": {"values": ["bug"], "exclusive": True}}}
    calls = []
    monkeypatch.setattr(api, "request", lambda path: calls.append(path) or {"encoding": "base64", "content": base64.b64encode(json.dumps(document).encode()).decode()})
    assert api.file_json(".github/prow.yaml", "a" * 40) == document
    assert calls == ["contents/.github/prow.yaml?ref=" + "a" * 40]


def test_applied_transition_uses_shared_renderer(catalog, event, monkeypatch):
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    api.current = set(state["expected"])
    rendered = []
    monkeypatch.setattr(prow, "prow_report", lambda catalog, report: rendered.append(deepcopy(report)) or "Applied report")
    report = prow.finish(state, catalog, api, "success")
    assert report["outcome"] == "applied"
    assert rendered == [report]
    assert api.calls[-1] == ("POST", "issues/12/comments", {"body": "Applied report"})


def test_pr_feedback_does_not_instruct_issue_acceptance(catalog, event, monkeypatch):
    event["issue"]["pull_request"] = {"url": "https://api.github.com/example"}
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    rendered = []
    monkeypatch.setattr(prow, "prow_report", lambda catalog, report: rendered.append(deepcopy(report)) or "PR report")
    report = prow.finish(state, catalog, api, "skipped")
    assert report["pull_request"] is True
    assert "triage/accepted" not in " ".join(report["next_steps"])
    assert rendered == [report]


def test_case_insensitive_labels_use_actual_api_casing(catalog, event):
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    after = {"Kind/Feature" if label == "kind/feature" else label for label in state["expected"]}
    report = prow.observed_result(state, catalog, after, "success")
    assert report["outcome"] == "applied"
    assert report["changes"]["add"] == ["Kind/Feature"]


@pytest.mark.parametrize("actions,repository", [("false", "projectbluefin/example"), ("true", "projectbluefin/elsewhere")])
def test_local_or_other_repository_write_refused(catalog, tmp_path, monkeypatch, actions, repository):
    path = tmp_path / "issue-policy.json"
    path.write_text(json.dumps(catalog))
    monkeypatch.setenv("GITHUB_ACTIONS", actions)
    monkeypatch.setenv("GITHUB_REPOSITORY", repository)
    with pytest.raises(ValueError, match="require GitHub Actions"):
        prow.main(["prepare", "--catalog", str(path)])


def test_catalog_commands_exclude_protected_operational_signals(catalog):
    assert prow.family_values(catalog, "kind") == ["bug", "debt", "feature", "task"]
    assert prow.expected_config(catalog)["labels"]["kind"]["values"] == ["bug", "debt", "feature", "task"]
    assert "tech-debt" not in " ".join(prow.supported_commands(catalog))
    # Even a direct configuration derivation cannot expose a protected shadow definition.
    catalog["labels"]["kind/tech-debt"] = {}
    assert "tech-debt" not in prow.family_values(catalog, "kind")


@pytest.mark.parametrize("signal", ["kind/tech-debt", "Kind/Tech-Debt"])
@pytest.mark.parametrize("command", ["/kind debt", "/kind bug"])
def test_protected_kind_denies_upstream_before_any_mutation(catalog, event, signal, command):
    event["comment"]["body"] = command
    api = FixtureGitHub(catalog, event)
    api.current.update({signal, "source:agent"})
    original = set(api.current)
    # Denial must precede even the required-definition read, not execute then report loss.
    api.error_path = "labels"
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert "upstream_command" not in state and "config" not in state
    assert state["result"]["outcome"] == "denied"
    assert state["result"]["changes"] == {"add": [], "remove": []}
    assert signal in state["result"]["reason"]
    instructions = " ".join(state["result"]["next_steps"])
    assert "GitHub's Labels picker" in instructions
    assert "select kind/" + command.split()[1] in instructions
    assert "deselect only other managed primary kinds" in instructions
    assert signal in instructions and "independent" in instructions
    assert api.current == original
    assert all(method == "GET" for method, _, _ in api.calls)


def test_command_cannot_assign_operational_debt_signal(catalog, event):
    event["comment"]["body"] = "/kind tech-debt"
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    assert not state["execute"]
    assert state["result"]["outcome"] == "invalid"
    assert state["result"]["changes"] == {"add": [], "remove": []}


@pytest.mark.parametrize("command", ["/area docs", "/remove-area api", "/hold", "/hold cancel"])
def test_safe_nonkind_commands_preserve_protected_operational_signals(catalog, event, command):
    event["comment"]["body"] = command
    api = FixtureGitHub(catalog, event)
    api.current.update({"kind/tech-debt", "source:agent", "area/api"})
    state = prow.prepare(event, catalog, api)
    assert state["execute"]
    assert {"kind/tech-debt", "source:agent"} <= set(state["expected"])


def test_safe_debt_command_without_protected_kind_preserves_other_operational_labels(catalog, event):
    event["comment"]["body"] = "/kind debt"
    api = FixtureGitHub(catalog, event)
    api.current.add("source:agent")
    state = prow.prepare(event, catalog, api)
    assert state["execute"]
    assert set(state["expected"]) == (api.current - {"kind/bug"}) | {"kind/debt"}


def test_upstream_config_cannot_reenable_operational_kind(catalog, event):
    api = FixtureGitHub(catalog, event)
    api.config["labels"]["kind"]["values"].append("tech-debt")
    assert not prow.prepare(event, catalog, api)["execute"]
