"""Notification authority, request identity and report input invariants."""

from copy import deepcopy

import pytest

from issue_status import prow_report, status_report


@pytest.fixture
def catalog():
    return {
        "repository": "projectbluefin/common",
        "display_name": "Common",
        "comment_marker": "<!-- common-issue-lifecycle:v1 -->",
        "delivery": {"type": "image"},
    }


@pytest.fixture
def record():
    return {
        "number": 42,
        "labels": ["needs-triage", "kind/bug"],
        "assignees": [],
        "user": {"type": "User", "login": "reporter"},
    }


@pytest.fixture
def facts():
    return {"comments": [], "linked_prs": [], "permissions": {"maintainer": "write"}}


@pytest.fixture
def context():
    return {
        "stage": "needs-triage", "approved": False, "tracking": False,
        "human_only": False, "automatic_gate": True, "missing": [],
        "requester": "reporter", "delivery_evidence": None, "close": False,
        "request_event": {"id": 1, "created_at": "2026-10-01T00:00:00Z", "actor": {"type": "User", "login": "maintainer"}},
    }


@pytest.fixture
def evidence():
    return {
        "image": "ghcr.io/projectbluefin/test@sha256:" + "a" * 64,
        "revision": "b" * 40,
        "url": "https://github.com/projectbluefin/test/releases/tag/test",
        "verify": "Repeat the reproduction steps and check the reported behavior.",
    }


def request_comment(number=10, **overrides):
    return {
        "id": number, "created_at": "2026-10-01T00:00:00Z",
        "html_url": f"https://github.com/projectbluefin/common/issues/42#issuecomment-{number}",
        "user": {"type": "User", "login": "maintainer"},
        "body": "@reporter Please provide the exact reproduction steps?", **overrides,
    }


@pytest.mark.parametrize("stage", ["needs-triage", "triage/accepted", "awaiting-release"])
def test_nonrequest_stages_do_not_notify_reporter(record, facts, catalog, context, stage):
    context["stage"] = stage
    result = status_report(record, facts, catalog, context)
    assert not result["notify_reporter"]
    assert result["notification_action"] is None


def test_information_identity_tracks_missing_fields_not_their_order(record, facts, catalog, context):
    context.update(stage="triage/needs-information", missing=["image details", "steps to reproduce"])
    result = status_report(record, facts, catalog, context)
    assert result["notify_reporter"]
    reordered = {**context, "missing": list(reversed(context["missing"]))}
    assert status_report(record, facts, catalog, reordered)["notification_action"] == result["notification_action"]
    changed = {**context, "missing": ["what happened?"]}
    assert status_report(record, facts, catalog, changed)["notification_action"] != result["notification_action"]


@pytest.mark.parametrize("missing", [[], ["image details"]])
def test_maintainer_decision_never_pings_reporter(record, facts, catalog, context, missing):
    context.update(stage="triage/needs-information", requester="maintainer", missing=missing)
    facts["comments"] = [request_comment()]
    result = status_report(record, facts, catalog, context)
    assert not result["notify_reporter"]
    assert result["notification_action"] is None


def test_unclear_information_request_does_not_notify(record, facts, catalog, context):
    context["stage"] = "triage/needs-information"
    result = status_report(record, facts, catalog, context)
    assert not result["notify_reporter"]
    assert result["notification_action"] is None


def test_latest_authorized_question_controls_the_request(record, facts, catalog, context):
    context["stage"] = "triage/needs-information"
    old = request_comment()
    new = request_comment(11, created_at="2026-10-02T00:00:00Z")
    facts["comments"] = [new, old]
    result = status_report(record, facts, catalog, context)
    assert result["notify_reporter"]
    assert new["html_url"] in result["comment"]
    assert old["html_url"] not in result["comment"]
    old_identity = status_report(record, {**facts, "comments": [old]}, catalog, context)["notification_action"]
    assert result["notification_action"] != old_identity


@pytest.mark.parametrize("comment", [
    request_comment(user={"type": "User", "login": "outsider"}),
    request_comment(user={"type": "Bot", "login": "maintainer"}),
    request_comment(body="<!-- common-issue-lifecycle:v1 --> Please answer?"),
    request_comment(body="This issue uses the factory issue pipeline. Please answer?"),
])
def test_untrusted_or_status_comment_cannot_request_reporter(record, facts, catalog, context, comment):
    context["stage"] = "triage/needs-information"
    facts["comments"] = [comment]
    assert not status_report(record, facts, catalog, context)["notify_reporter"]


def test_request_identity_ignores_display_and_bot_projection(record, facts, catalog, context):
    context["stage"] = "triage/needs-information"
    facts["comments"] = [request_comment()]
    original = status_report(record, facts, catalog, context)
    facts["comments"].append(request_comment(100, user={"type": "Bot", "login": "github-actions[bot]"}))
    catalog["display_name"] = "Renamed"
    changed = status_report(record, facts, catalog, context)
    assert changed["notification_action"] == original["notification_action"]


def test_tracker_never_requests_reporter_information(record, facts, catalog, context):
    context.update(stage="triage/needs-information", tracking=True, missing=["steps to reproduce"])
    result = status_report(record, facts, catalog, context)
    assert not result["notify_reporter"]
    assert result["notification_action"] is None


def test_delivery_request_identity_changes_only_with_delivery_target(record, facts, catalog, context, evidence):
    context.update(stage="needs-verification", delivery_evidence=evidence)
    original = status_report(record, facts, catalog, context)
    assert original["notify_reporter"]
    reformatted = {**evidence, "verify": "**Repeat** the reproduction steps and check the reported behavior."}
    assert status_report(record, facts, catalog, {**context, "delivery_evidence": reformatted})["notification_action"] == original["notification_action"]
    changed = {**evidence, "image": "new-published-image"}
    assert status_report(record, facts, catalog, {**context, "delivery_evidence": changed})["notification_action"] != original["notification_action"]


@pytest.mark.parametrize("delivery", [None, {"url": "https://example.test/release"}])
def test_incomplete_delivery_cannot_request_reporter_verification(record, facts, catalog, context, delivery):
    context.update(stage="needs-verification", delivery_evidence=delivery)
    result = status_report(record, facts, catalog, context)
    assert not result["notify_reporter"]
    assert result["notification_action"] is None


def test_completed_confirmation_does_not_renotify_reporter(record, facts, catalog, context, evidence):
    context.update(stage="needs-verification", close=True, delivery_evidence=evidence)
    result = status_report(record, facts, catalog, context)
    assert not result["notify_reporter"]
    assert result["notification_action"] is None


@pytest.mark.parametrize("stage,delivery", [
    ("triage/accepted", {"image": "test"}),
    ("needs-verification", None),
    ("needs-verification", {"image": "test"}),
])
def test_invalid_close_context_cannot_claim_completed_fix(record, facts, catalog, context, stage, delivery):
    context.update(stage=stage, close=True, delivery_evidence=delivery)
    with pytest.raises(ValueError):
        status_report(record, facts, catalog, context)


@pytest.mark.parametrize("user_type", ["Bot", None])
def test_nonhuman_reporter_has_no_targeted_notification(record, facts, catalog, context, user_type):
    record["user"] = {"login": "actor", "type": user_type}
    context.update(stage="triage/needs-information", missing=["steps to reproduce"])
    result = status_report(record, facts, catalog, context)
    assert not result["notify_reporter"]
    assert result["notification_action"] is None


def test_reporting_does_not_mutate_assignment_or_policy_inputs(record, facts, catalog, context):
    originals = deepcopy((record, facts, catalog, context))
    status_report(record, facts, catalog, context)
    assert (record, facts, catalog, context) == originals


@pytest.mark.parametrize("invalid", ["stage", "delivery", "outcome"])
def test_unknown_policy_values_are_rejected_without_guessed_status(record, facts, catalog, context, invalid):
    with pytest.raises(ValueError):
        if invalid == "outcome":
            prow_report(catalog, {"command": "/help", "outcome": "success-maybe"})
        else:
            if invalid == "stage":
                context["stage"] = "done-maybe"
            else:
                catalog["delivery"] = {"type": "unspecified"}
            status_report(record, facts, catalog, context)


@pytest.mark.parametrize("body,created", [
    ("@release-owner please confirm publication; reporter need not act", "2026-10-02T00:00:00Z"),
    ("@reporter Please provide more details?", "2026-09-30T00:00:00Z"),
    ("Please provide more details?", "2026-10-02T00:00:00Z"),
])
def test_information_request_requires_current_reporter_recipient(record, facts, catalog, context, body, created):
    context["stage"] = "triage/needs-information"
    facts["comments"] = [request_comment(body=body, created_at=created)]
    result = status_report(record, facts, catalog, context)
    assert not result["notify_reporter"]
    assert result["notification_action"] is None


def test_ask_then_picker_pairing_notifies_explicit_reporter(record, facts, catalog, context):
    context["stage"] = "triage/needs-information"
    context["request_event"]["created_at"] = "2026-10-01T00:02:00Z"
    facts["comments"] = [request_comment()]
    assert status_report(record, facts, catalog, context)["notify_reporter"]


def test_answered_question_cannot_request_reporter_again(record, facts, catalog, context):
    context["stage"] = "triage/needs-information"
    facts["comments"] = [request_comment(), request_comment(11, created_at="2026-10-01T00:01:00Z", user={"type": "User", "login": "reporter"}, body="Here are the details")]
    assert not status_report(record, facts, catalog, context)["notify_reporter"]
