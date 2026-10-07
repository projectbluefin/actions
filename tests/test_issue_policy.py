"""Consumer-visible common lifecycle transitions and authorization boundaries."""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import issue_policy as policy

CATALOG = {'repository': 'projectbluefin/common', 'stages': {'needs-triage': {'color': 'ededed', 'description': 'Awaiting a maintainer assessment; not implementation approval.'}, 'triage/needs-information': {'color': 'd455d0', 'description': 'Waiting for the specific information or decision requested in the issue.'}, 'triage/accepted': {'color': '8fc951', 'description': 'A trusted maintainer accepted the current scope for implementation.'}, 'awaiting-release': {'color': 'fbca04', 'description': 'The accepted fix is merged; delivery to the affected image is still pending.'}, 'needs-verification': {'color': 'c2e0c6', 'description': 'Verified delivery evidence is recorded; the reporter should test the fix.'}}, 'labels': {'needs-kind': {'color': 'ededed', 'description': 'A maintainer must classify this issue; the intake source did not establish its kind.'}, 'kind/bug': {'color': 'd73a4a', 'description': 'Something is broken or behaves incorrectly.'}, 'kind/feature': {'color': 'c7def8', 'description': 'A requested capability or enhancement.'}, 'kind/task': {'color': 'c5def5', 'description': 'An explicit maintenance task or standing tracking issue.'}, 'human-only': {'color': 'a467dc', 'description': 'Human interaction only: no machine analysis or agent implementation.'}, 'needs-human': {'color': 'd455d0', 'description': 'Human input is required before Hive may start new implementation work.'}, 'tracking': {'color': '8b949e', 'description': 'Standing dashboard or portfolio tracker, not an implementation task.'}}, 'retired_stages': ['1-triage', '2-discussing', '3-human-queue', '3-clanker-queue', '4-review', 'status/discussing', 'status/queued', 'status/claimed', 'queue/agent-ready', 'queue/claimed'], 'standing_issues': [245, 639, 972, 1209, 1210], 'display_name': 'Common', 'comment_marker': '<!-- common-issue-lifecycle:v1 -->', 'delivery': {'type': 'image'}, 'label_aliases': {}}
CATALOG["bug_fields"] = ["what happened?", "what did you expect?", "steps to reproduce", "image details"]
CATALOG["feature_fields"] = ["problem to solve", "desired outcome", "affected component"]
T0 = "2026-10-02T10:00:00Z"
T1 = "2026-10-02T11:00:00Z"
T2 = "2026-10-02T12:00:00Z"


def issue(labels=(), body="", number=10):
    return {
        "number": number,
        "state": "open",
        "body": body,
        "labels": list(labels),
        "user": {"login": "reporter", "type": "User"},
        "assignees": [],
        "updated_at": T0,
    }


def event(label, actor="maintainer", kind="User", time=T1, action="labeled"):
    return {
        "event": action,
        "label": {"name": label},
        "actor": {"login": actor, "type": kind},
        "created_at": time,
        "id": 1,
    }


def facts(timeline=(), comments=(), edited=None, prs=()):
    return {
        "timeline": list(timeline),
        "comments": list(comments),
        "last_edited_at": edited,
        "permissions": {"maintainer": "maintain", "outsider": "read"},
        "linked_prs": list(prs),
    }


def reply(text, actor="reporter", kind="User", time=T2):
    return {
        "id": 2,
        "body": text,
        "created_at": time,
        "html_url": "https://github.com/projectbluefin/common/issues/10#issuecomment-2",
        "user": {"login": actor, "type": kind},
    }


def final_labels(record, result):
    return (policy.labels_of(record) - set(result["remove"])) | set(result["add"])


def accepted(labels=()):
    return issue(("triage/accepted", "kind/feature", *labels)), facts(
        (event("triage/accepted"),)
    )


def delivery_body():
    return (
        "### Delivery evidence\nImage: ghcr.io/projectbluefin/utah:stable@sha256:"
        + "a" * 64
        + "\nFix revision: "
        + "b" * 40
        + "\nRelease/build: https://github.com/projectbluefin/utah/actions/runs/1\nVerify: repeat the original reproduction steps.\n"
    )


def test_noncollaborator_report_is_initialized_from_body_not_client_labels():
    record = issue(
        body="<!-- report-type: bug -->\n<!-- automation-preference: human-only -->\n### Summary\nBroken update\n"
    )
    result = policy.plan(record, facts(), CATALOG)
    assert final_labels(record, result) == {
        "needs-triage",
        "kind/bug",
        "human-only",
        "needs-human",
    }
    assert not result["close"]


@pytest.mark.parametrize("label", ["3-clanker-queue", "1-triage", "4-review"])
def test_legacy_queue_is_not_implementation_approval(label):
    record = issue((label, "kind/feature"))
    result = policy.plan(record, facts(), CATALOG, migrate=True)
    assert final_labels(record, result) == {
        "needs-triage",
        "kind/feature",
        "needs-human",
    }


def test_old_human_queue_preference_survives_retirement():
    record = issue(("3-human-queue", "kind/bug"))
    result = policy.plan(record, facts(), CATALOG, migrate=True)
    assert final_labels(record, result) == {
        "needs-triage",
        "kind/bug",
        "human-only",
        "needs-human",
    }


@pytest.mark.parametrize(
    "actor,kind,permission",
    [("outsider", "User", "read"), ("agent[bot]", "Bot", "admin")],
)
def test_forged_acceptance_cannot_release_native_hive_gate(actor, kind, permission):
    record = issue(("triage/accepted", "needs-human", "kind/bug"))
    data = facts((event("triage/accepted", actor, kind),))
    data["permissions"][actor] = permission
    result = policy.plan(record, data, CATALOG)
    assert final_labels(record, result) == {"needs-triage", "needs-human", "kind/bug"}


def test_authenticated_maintainer_acceptance_releases_gate():
    record, data = accepted(("needs-human",))
    data["timeline"].insert(
        0, event("needs-human", "github-actions[bot]", "Bot", time=T0)
    )
    result = policy.plan(record, data, CATALOG)
    assert final_labels(record, result) == {"triage/accepted", "kind/feature"}


def test_hive_decision_pauses_accepted_work_and_resolving_it_resumes():
    # Reproduces common#1385: Hive asks for a decision on accepted work, then clears it.
    record, data = accepted(("needs-decision",))
    data["timeline"].append(event("needs-decision", "hivecommons-hive[bot]", "Bot", time=T2))
    paused = policy.plan(record, data, CATALOG)
    assert paused["stage"] == "triage/accepted"
    assert final_labels(record, paused) == {"triage/accepted", "kind/feature", "needs-decision", "needs-human"}
    record["labels"] = ["triage/accepted", "kind/feature", "needs-human"]
    data["timeline"] += [
        event("needs-human", "github-actions[bot]", "Bot", time=T2),
        event("needs-decision", "hivecommons-hive[bot]", "Bot", time="2026-10-02T13:00:00Z", action="unlabeled"),
    ]
    resumed = policy.plan(record, data, CATALOG)
    assert final_labels(record, resumed) == {"triage/accepted", "kind/feature"}


def test_decision_before_acceptance_still_waits_for_information():
    record = issue(("needs-triage", "kind/feature", "needs-decision"))
    result = policy.plan(record, facts(), CATALOG)
    assert result["stage"] == "triage/needs-information"
    assert "needs-human" in final_labels(record, result)




def test_trusted_removal_of_human_only_waives_body_preference():
    body = (
        "### Automation preference\nHuman interaction only\n"
        "### What happened?\nBug\n"
        "### What did you expect?\nFix\n"
        "### Steps to reproduce\n1. Run\n"
        "### Image details\nbluefin:stable\n"
    )
    record = issue(
        ("triage/accepted", "needs-human", "kind/bug"),
        body=body,
    )
    data = facts(
        (
            event("needs-human", "github-actions[bot]", "Bot", time=T0),
            event("human-only", "github-actions[bot]", "Bot", time=T0),
            event("triage/accepted", "maintainer", "User", time=T1),
            event("human-only", "maintainer", "User", time=T2, action="unlabeled"),
        )
    )
    result = policy.plan(record, data, CATALOG)
    # Acceptance stands, human-only is waived, and the automatic needs-human gate releases
    assert final_labels(record, result) == {"triage/accepted", "kind/bug"}


def test_untrusted_removal_of_human_only_does_not_waive_preference():
    body = (
        "### Automation preference\nHuman interaction only\n"
        "### What happened?\nBug\n"
        "### What did you expect?\nFix\n"
        "### Steps to reproduce\n1. Run\n"
        "### Image details\nbluefin:stable\n"
    )
    record = issue(
        ("triage/accepted", "needs-human", "kind/bug"),
        body=body,
    )
    data = facts(
        (
            event("needs-human", "github-actions[bot]", "Bot", time=T0),
            event("human-only", "github-actions[bot]", "Bot", time=T0),
            event("triage/accepted", "maintainer", "User", time=T1),
            event("human-only", "outsider", "User", time=T2, action="unlabeled"),
        )
    )
    result = policy.plan(record, data, CATALOG)
    # Outsider removal is ignored; body preference restores human-only and keeps needs-human
    assert final_labels(record, result) == {"triage/accepted", "kind/bug", "human-only", "needs-human"}


def test_re_adding_human_only_after_trusted_removal_restores_gate():
    record = issue(
        ("triage/accepted", "needs-human", "kind/bug", "human-only"),
        body="### Automation preference\nHuman interaction only\n### What happened?\nBug",
    )
    data = facts(
        (
            event("human-only", "maintainer", "User", time=T1, action="unlabeled"),
            event("human-only", "maintainer", "User", time=T2, action="labeled"),
            event("triage/accepted", "maintainer", "User", time=T2),
        )
    )
    result = policy.plan(record, data, CATALOG)
    assert "human-only" in final_labels(record, result)
    assert "needs-human" in final_labels(record, result)
def test_edited_spec_revokes_acceptance_without_reassigning_work():
    record, data = accepted()
    record["assignees"] = [{"login": "contributor"}]
    data["last_edited_at"] = T2
    result = policy.plan(record, data, CATALOG)
    assert final_labels(record, result) == {
        "needs-triage",
        "kind/feature",
        "needs-human",
    }
    assert record["assignees"] == [{"login": "contributor"}]


def test_explicit_withdrawal_is_not_resurrected_by_old_approval():
    record = issue(("needs-triage", "kind/feature"))
    data = facts(
        (
            event("triage/accepted"),
            event("triage/accepted", time=T2, action="unlabeled"),
        )
    )
    result = policy.plan(record, data, CATALOG)
    assert "triage/accepted" not in final_labels(record, result)
    assert "needs-human" in final_labels(record, result)


def test_unreadable_edit_history_fails_closed():
    record, data = accepted()
    del data["last_edited_at"]
    assert policy.plan(record, data, CATALOG)["stage"] == "needs-triage"


@pytest.mark.parametrize("overlay", ["blocked", "hold", "human-only"])
def test_negative_overlay_outweighs_human_acceptance(overlay):
    record, data = accepted((overlay, "needs-human"))
    result = policy.plan(record, data, CATALOG)
    assert {overlay, "needs-human", "triage/accepted"} <= final_labels(record, result)


def test_all_orthogonal_labels_and_both_overlays_survive_migration():
    preserve = {
        "blocked",
        "hold",
        "hive/hosted-projectbluefin-knuckle-gjvq",
        "agent/security",
        "security",
        "quality",
        "lgtm",
        "automerge",
    }
    record = issue((*preserve, "1-triage", "3-clanker-queue"))
    result = policy.plan(record, facts(), CATALOG, migrate=True)
    assert preserve <= final_labels(record, result)
    assert final_labels(record, result) & set(CATALOG["stages"]) == {"needs-triage"}


def test_bot_reply_cannot_clear_information_request():
    record = issue(("triage/needs-information", "kind/bug"))
    data = facts(
        (event("triage/needs-information"),),
        (reply("Collected evidence", "agent[bot]", "Bot"),),
    )
    assert policy.plan(record, data, CATALOG)["stage"] == "triage/needs-information"


def test_reporter_reply_returns_to_triage_not_approval():
    record = issue(("triage/needs-information", "kind/bug"))
    data = facts(
        (event("triage/needs-information"),), (reply("Here are the requested details"),)
    )
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "needs-triage"
    assert "needs-human" in final_labels(record, result)


def test_unknown_kind_is_flagged_without_guessing_from_title():
    record = issue()
    record["title"] = "A bug and a feature"
    result = policy.plan(record, facts(), CATALOG)
    assert final_labels(record, result) == {"needs-triage", "needs-kind", "needs-human"}


def test_feature_request_does_not_demand_bootc_or_diagnostics():
    body = "### Problem to solve\nA task is difficult\n### Desired outcome\nMake it easier\n### Affected component\nujust\n"
    record = issue(body=body)
    result = policy.plan(record, facts(), CATALOG)
    assert final_labels(record, result) == {
        "needs-triage",
        "kind/feature",
        "needs-human",
    }
    assert "bootc status" not in result["comment"]


def test_missing_image_details_requests_actionable_command():
    body = "### What happened?\nAn update fails\n### What did you expect?\nSuccessful update\n### Steps to reproduce\nRun update\n### Image details\n_No response_\n"
    result = policy.plan(issue(body=body), facts(), CATALOG)
    assert result["stage"] == "triage/needs-information"
    assert "Run `bootc status` and paste the complete output" in result["comment"]


def test_standing_tracker_is_not_dispatched_or_forced_into_bug_form():
    record = issue(("3-clanker-queue",), number=245)
    result = policy.plan(record, facts(), CATALOG, migrate=True)
    assert final_labels(record, result) == {
        "needs-triage",
        "kind/task",
        "tracking",
        "needs-human",
    }


def test_pr_cleanup_preserves_review_and_merge_labels_without_issue_stage():
    record = issue(("3-human-queue", "3-clanker-queue", "hold", "lgtm", "kind/feature"))
    record["pull_request"] = {
        "url": "https://api.github.com/repos/projectbluefin/common/pulls/10"
    }
    result = policy.plan(record, facts(), CATALOG)
    assert final_labels(record, result) == {"hold", "lgtm", "kind/feature"}
    assert result["stage"] is None
    assert not result["close"]


def test_closed_issue_is_not_reopened_or_posted_to():
    record = issue(("1-triage",))
    record["state"] = "closed"
    result = policy.plan(record, facts(), CATALOG)
    assert result["comment"] is None
    assert not result["close"]
    assert record["state"] == "closed"


def test_merged_fix_does_not_claim_image_delivery_or_close_report():
    record, data = accepted()
    record["body"] = "### Image details\nghcr.io/projectbluefin/utah:testing\n"
    record["labels"].append("awaiting-release")
    data["timeline"].append(event("awaiting-release", time=T2))
    data["linked_prs"] = [
        {
            "number": 20,
            "merged_at": T2,
            "body": "Refs #10",
            "html_url": "https://github.com/projectbluefin/common/pull/20",
        }
    ]
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "awaiting-release"
    assert not result["close"]
    assert "needs-human" in final_labels(record, result)


def test_cross_repo_same_number_is_not_local_implementation_link():
    assert policy.referenced_issues(
        "Closes projectbluefin/dakota#10\nRefs https://github.com/projectbluefin/utah/issues/10\nRefs #12", CATALOG["repository"]
    ) == {12}


def test_missing_delivery_receipt_does_not_request_verification():
    record = issue(("needs-verification", "kind/bug"))
    data = facts((event("needs-verification"),))
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "awaiting-release"
    assert not result["close"]


def test_bot_cannot_forge_published_delivery_state():
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts((event("needs-verification", "agent[bot]", "Bot"),))
    assert policy.plan(record, data, CATALOG)["stage"] == "needs-triage"


def test_published_receipt_requests_specific_reporter_verification():
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts((event("needs-verification"),))
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "needs-verification"
    assert "repeat the original reproduction steps" in result["comment"]
    assert "sha256:" + "a" * 64 in result["comment"]
    assert not result["close"]


@pytest.mark.parametrize("actor,kind", [("outsider", "User"), ("agent[bot]", "Bot")])
def test_other_actor_cannot_confirm_on_reporters_behalf(actor, kind):
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts(
        (event("needs-verification"),), (reply("Confirmed fixed", actor, kind),)
    )
    assert not policy.plan(record, data, CATALOG)["close"]


def test_negative_confirmation_reopens_triage_without_restarting_work():
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts(
        (event("needs-verification"),), (reply("Still broken on the published image"),)
    )
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "needs-triage"
    assert not result["close"]


def test_explicit_reporter_confirmation_closes_verified_report():
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts(
        (event("needs-verification"),),
        (reply("Confirmed fixed in the release linked above"),),
    )
    assert policy.plan(record, data, CATALOG)["close"]


def test_earlier_confirmation_cannot_close_a_new_verification_request():
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts(
        (event("needs-verification", time=T2),), (reply("Confirmed fixed", time=T0),)
    )
    assert not policy.plan(record, data, CATALOG)["close"]


def test_write_client_rejects_every_other_repository():
    with pytest.raises(ValueError, match="only writes projectbluefin/common"):
        policy.GitHub("projectbluefin/dakota", CATALOG)


@pytest.mark.parametrize("pull_request", [False, True])
def test_collected_issue_and_pr_drive_the_public_policy(monkeypatch, pull_request):
    record = issue(("kind/bug",), "<!-- report-type: bug -->")
    record["html_url"] = "https://github.com/projectbluefin/common/" + (
        "pull/10" if pull_request else "issues/10"
    )
    if pull_request:
        record["pull_request"] = {
            "url": "https://api.github.com/repos/projectbluefin/common/pulls/10"
        }
    responses = {
        "repos/projectbluefin/common/issues/10": record,
        "repos/projectbluefin/common/issues/10/comments?per_page=100": [],
        "repos/projectbluefin/common/issues/10/timeline?per_page=100": [],
        "repos/projectbluefin/common/pulls/10": {"draft": True},
        "graphql": {
            "data": {
                "repository": {
                    "issue": {"lastEditedAt": None},
                    "pullRequest": {
                        "reviewDecision": "REVIEW_REQUIRED",
                        "mergeable": "MERGEABLE",
                    },
                }
            }
        },
    }
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    monkeypatch.setattr(
        client, "request", lambda method, path, body=None, **kwargs: responses[path]
    )
    collected, data = client.collect(10)
    result = policy.plan(collected, data, CATALOG)
    if pull_request:
        assert result["stage"] is None
        assert final_labels(collected, result) == {"kind/bug"}
        assert "Ready for review" in result["comment"]
    else:
        assert result["stage"] == "needs-triage"
        assert final_labels(collected, result) == {
            "needs-triage",
            "kind/bug",
            "needs-human",
        }


def test_information_reply_is_not_lost_during_periodic_reconciliation():
    body = "### What happened?\nBroken\n### What did you expect?\nWorking\n### Steps to reproduce\nRun it\n### Image details\n_No response_\n"
    record = issue(("needs-triage", "kind/bug"), body)
    data = facts(
        (event("triage/needs-information"),), (reply("I cannot boot the machine"),)
    )
    assert policy.plan(record, data, CATALOG)["stage"] == "needs-triage"


def test_unclassified_acceptance_stays_out_of_agent_dispatch():
    record = issue(("triage/accepted",))
    result = policy.plan(record, facts((event("triage/accepted"),)), CATALOG)
    assert {"needs-kind", "needs-human"} <= final_labels(record, result)


def test_client_cannot_write_other_repo_even_with_a_forged_api_path():
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    with pytest.raises(ValueError, match="Write outside projectbluefin/common refused"):
        client.request(
            "POST",
            "repos/projectbluefin/dakota/issues/10/labels",
            {"labels": ["needs-triage"]},
        )


def test_repeated_migration_does_not_turn_managed_gate_into_human_only():
    record = issue(("needs-triage", "kind/feature", "needs-human"))
    result = policy.plan(record, facts(), CATALOG, migrate=True)
    assert "human-only" not in final_labels(record, result)


@pytest.mark.parametrize(
    "native,actor",
    [
        ({"review_decision": "CHANGES_REQUESTED"}, "PR contributor"),
        ({"native_mergeable": "CONFLICTING"}, "PR contributor"),
        ({"review_decision": "APPROVED"}, "PR contributor"),
    ],
)
def test_pr_next_actor_follows_native_state(native, actor):
    record = issue()
    record["pull_request"] = {
        "url": "https://api.github.com/repos/projectbluefin/common/pulls/10"
    }
    data = facts()
    data["pull_request"] = native
    result = policy.plan(record, data, CATALOG)
    assert "## PR contributor" in result["comment"]
    assert not result["notify_reporter"]
    assert result["add"] == []


def test_code_only_fix_does_not_wait_for_an_image_release():
    record, data = accepted()
    record["body"] = "### Image details\nNot applicable: this is a repository script\n"
    data["linked_prs"] = [
        {
            "number": 20,
            "merged_at": T2,
            "body": "Refs #10",
            "html_url": "https://github.com/projectbluefin/common/pull/20",
        }
    ]
    assert policy.plan(record, data, CATALOG)["stage"] == "triage/accepted"


def test_stale_body_is_rejected_even_when_timestamp_has_not_advanced(monkeypatch):
    record = issue(("needs-triage",), "Original scope")
    record["html_url"] = "https://github.com/projectbluefin/common/issues/10"
    fresh = {**record, "body": "Changed scope"}
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    writes = []

    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return fresh
        writes.append((method, path, body))

    monkeypatch.setattr(client, "request", request)
    with pytest.raises(RuntimeError, match="changed during reconciliation"):
        client.apply(record, facts(), policy.plan(record, facts(), CATALOG))
    assert writes == []


def test_snapshot_cannot_be_used_to_mint_live_acceptance(tmp_path):
    snapshot = tmp_path / "forged.json"
    snapshot.write_text("[]")
    with pytest.raises(SystemExit) as error:
        policy.main(["--snapshot", str(snapshot), "--apply"])
    assert error.value.code == 2


def test_editing_requested_information_returns_to_assessment():
    record = issue(("triage/needs-information", "kind/bug"), "Updated report details")
    data = facts((event("triage/needs-information"),), edited=T2)
    assert policy.plan(record, data, CATALOG)["stage"] == "needs-triage"


@pytest.mark.parametrize(
    "author,actor_type", [("maintainer", "User"), ("github-actions[bot]", "Bot")]
)
def test_only_bot_history_is_upgraded_and_reporter_forgery_is_untouched(
    monkeypatch, author, actor_type
):
    record = issue(("1-triage", "kind/feature"))
    record["html_url"] = "https://github.com/projectbluefin/common/issues/10"
    old = reply(
        "This issue has been marked `status/discussing` as part of the factory issue pipeline.\nUse old approval commands.",
        actor=author,
        kind=actor_type,
    )
    old["id"] = 7
    original = old["body"]
    forged = reply(CATALOG["comment_marker"] + "Fake accepted state", actor="reporter")
    forged["id"] = 8
    data = facts(comments=(old, forged))
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    posted = []

    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return record
        if method == "PATCH" and path.endswith("/comments/7"):
            old["body"] = body["body"]
        if method == "POST" and path.endswith("/comments"):
            posted.append(body["body"])

    monkeypatch.setattr(client, "request", request)
    client.apply(record, data, policy.plan(record, data, CATALOG))
    if actor_type == "User":
        assert old["body"] == original
        assert posted[0].startswith(CATALOG["comment_marker"])
    else:
        assert old["body"].startswith(CATALOG["comment_marker"])
        assert posted == []
    assert forged["body"] == CATALOG["comment_marker"] + "Fake accepted state"


def test_native_gate_is_installed_before_retiring_old_queue(monkeypatch):
    record = issue(("3-clanker-queue", "kind/feature"))
    record["html_url"] = "https://github.com/projectbluefin/common/issues/10"
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    writes = []

    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return record
        writes.append((method, path, body))

    monkeypatch.setattr(client, "request", request)
    client.apply(record, facts(), policy.plan(record, facts(), CATALOG))
    assert writes[0][0] == "POST"
    assert "needs-human" in writes[0][2]["labels"]
    assert any(item[0] == "DELETE" for item in writes[1:])


def test_picker_information_request_supersedes_existing_stage():
    record = issue(("needs-triage", "triage/needs-information", "kind/bug"))
    data = facts((event("needs-triage", time=T0), event("triage/needs-information")))
    assert policy.plan(record, data, CATALOG)["stage"] == "triage/needs-information"


def test_picker_verification_supersedes_waiting_release_stage():
    record = issue(
        ("awaiting-release", "needs-verification", "kind/bug"), delivery_body()
    )
    data = facts((event("awaiting-release", time=T0), event("needs-verification")))
    result = policy.plan(record, data, CATALOG)
    assert final_labels(record, result) & set(CATALOG["stages"]) == {
        "needs-verification"
    }


def test_information_request_invalidates_old_acceptance_after_reporter_reply():
    record = issue(("triage/needs-information", "kind/feature", "needs-human"))
    data = facts(
        (event("triage/accepted", time=T0), event("triage/needs-information")),
        (reply("Here is the information"),),
    )
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "needs-triage"
    assert "needs-human" in final_labels(record, result)


def test_earlier_independent_human_gate_is_not_cleared_by_acceptance():
    record, data = accepted(("needs-human",))
    data["timeline"].insert(0, event("needs-human", time=T0))
    assert "needs-human" in final_labels(record, policy.plan(record, data, CATALOG))


def test_legacy_cli_merged_reference_keeps_accepted_scope_in_implementation():
    record = issue(
        ("triage/accepted",),
        "## Bluefin Bug Report\n### System\nImage: ghcr.io/projectbluefin/utah:testing\n",
    )
    data = facts(
        (event("triage/accepted"),),
        prs=(
            {
                "number": 20,
                "merged_at": T2,
                "body": "Refs #10",
                "html_url": "https://github.com/projectbluefin/common/pull/20",
            },
        ),
    )
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "triage/accepted"
    assert "kind/bug" in final_labels(record, result)
    assert "needs-human" not in final_labels(record, result)


def test_failed_verification_stays_in_assessment_on_next_sweep():
    record = issue(("needs-triage", "kind/bug", "needs-human"), delivery_body())
    data = facts(
        (
            event("triage/accepted", time=T0),
            event("needs-verification"),
            event("needs-triage", "github-actions[bot]", "Bot", time=T2),
        ),
        (reply("Still broken"),),
    )
    assert policy.plan(record, data, CATALOG)["stage"] == "needs-triage"


def test_same_second_spec_edit_is_not_assumed_approved():
    record, data = accepted()
    data["last_edited_at"] = T1
    assert policy.plan(record, data, CATALOG)["stage"] == "needs-triage"


def test_local_user_token_cannot_apply_migration(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(SystemExit) as error:
        policy.main(["--migrate", "--apply"])
    assert error.value.code == 2


def test_old_discussing_label_does_not_invent_a_reporter_information_request():
    record = issue(("2-discussing", "kind/feature"))
    result = policy.plan(record, facts(), CATALOG, migrate=True)
    assert result["stage"] == "needs-triage"
    assert result["comment"] is None


def test_action_request_notifies_reporter_once_and_keeps_one_status(monkeypatch):
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    record["html_url"] = "https://github.com/projectbluefin/common/issues/10"
    data = facts((event("needs-verification"),))
    previous = reply(
        CATALOG["comment_marker"] + "\nOld passive status",
        actor="github-actions[bot]",
        kind="Bot",
    )
    previous["id"] = 7
    data["comments"].append(previous)
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    notifications = []

    def request(method, path, body=None, **kwargs):
        if method == "GET" and "/timeline" in path:
            return data["timeline"]
        if method == "GET":
            return record
        if method == "PATCH" and "/comments/7" in path:
            previous["body"] = body["body"]
        if method == "POST" and path.endswith("/comments"):
            notification = reply(body["body"], actor="github-actions[bot]", kind="Bot")
            notifications.append(notification)
            data["comments"].append(notification)

    monkeypatch.setattr(client, "request", request)
    result = policy.plan(record, data, CATALOG)
    client.apply(record, data, result)
    client.apply(record, data, result)
    assert len(notifications) == 1
    assert "@reporter" in notifications[0]["body"]
    assert "sha256:" + "a" * 64 in notifications[0]["body"]
    assert previous["body"].startswith(CATALOG["comment_marker"])


def test_first_information_request_is_itself_the_notification(monkeypatch):
    body = "### What happened?\nBroken\n### What did you expect?\nWorking\n### Steps to reproduce\nRun it\n### Image details\n_No response_\n"
    record = issue(("triage/needs-information", "kind/bug"), body)
    record["html_url"] = "https://github.com/projectbluefin/common/issues/10"
    data = facts((event("triage/needs-information"),))
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    posted = []

    def request(method, path, body=None, **kwargs):
        if method == "GET" and "/timeline" in path:
            return data["timeline"]
        if method == "GET":
            return record
        if method == "POST" and path.endswith("/comments"):
            comment = reply(body["body"], actor="github-actions[bot]", kind="Bot")
            comment["id"] = 7
            data["comments"].append(comment)
            posted.append(comment)

    monkeypatch.setattr(client, "request", request)
    result = policy.plan(record, data, CATALOG)
    client.apply(record, data, result)
    client.apply(record, data, result)
    assert len(posted) == 1
    assert "@reporter" in posted[0]["body"]
    assert "bootc status" in posted[0]["body"]


@pytest.mark.parametrize("quiet_option", ["migrate", "labels_only"])
def test_quiet_repair_does_not_close_or_notify_verified_report(quiet_option):
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts(
        (event("needs-verification"),),
        (reply("Confirmed fixed in the release linked above"),),
    )
    assert policy.plan(record, data, CATALOG)["close"]
    result = policy.plan(record, data, CATALOG, **{quiet_option: True})
    assert not result["close"]
    assert result["comment"] is None
    assert final_labels(record, result) & set(CATALOG["stages"]) == {"needs-verification"}


@pytest.mark.parametrize("quiet_option", ["migrate", "labels_only"])
def test_quiet_repair_removes_pr_stages_without_commenting(quiet_option):
    record = issue(("1-triage", "needs-triage", "kind/bug", "hold"))
    record["pull_request"] = {}
    result = policy.plan(record, facts(), CATALOG, **{quiet_option: True})
    assert final_labels(record, result) == {"kind/bug", "hold"}
    assert result["comment"] is None
    assert not result["close"]


def test_unrelated_merged_reference_keeps_accepted_work_in_implementation():
    record = issue(("awaiting-release", "needs-human", "kind/bug"))
    record["body"] = "### Image details\nghcr.io/projectbluefin/dakota:testing\n"
    data = facts(
        (
            event("needs-human", "github-actions[bot]", "Bot", time=T0),
            event("triage/accepted"),
            event("awaiting-release", "github-actions[bot]", "Bot", time=T2),
            event(
                "triage/accepted", "github-actions[bot]", "Bot",
                time=T2, action="unlabeled",
            ),
        ),
        prs=(
            {
                "number": 20,
                "merged_at": T2,
                "state": "closed",
                "body": "Docs: explain the workflow. Refs #10",
                "html_url": "https://github.com/projectbluefin/common/pull/20",
            },
        ),
    )
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "triage/accepted"
    assert final_labels(record, result) == {"triage/accepted", "kind/bug"}
    assert not result["close"]


def test_bot_restoration_does_not_replace_the_valid_human_acceptance():
    record, data = accepted()
    data["timeline"].extend(
        (
            event(
                "triage/accepted", "github-actions[bot]", "Bot",
                time=T2, action="unlabeled",
            ),
            event("triage/accepted", "github-actions[bot]", "Bot", time=T2),
        )
    )
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "triage/accepted"
    assert final_labels(record, result) == {"triage/accepted", "kind/feature"}


def test_human_withdrawal_cannot_be_hidden_by_a_later_bot_removal():
    record, data = accepted()
    data["timeline"] = [
        event("triage/accepted", time=T0),
        event("triage/accepted", action="unlabeled"),
        event(
            "triage/accepted", "github-actions[bot]", "Bot",
            time=T2, action="unlabeled",
        ),
        event("triage/accepted", "github-actions[bot]", "Bot", time=T2),
    ]
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "needs-triage"
    assert "needs-human" in final_labels(record, result)


def release_catalog():
    catalog = copy.deepcopy(CATALOG)
    catalog.update(repository="projectbluefin/chairlift", display_name="ChairLift",
                   comment_marker="<!-- chairlift-issue-lifecycle:v1 -->",
                   delivery={"type": "release"}, standing_issues=[137])
    catalog["bug_fields"] = ["what happened?", "expected behavior", "reproduction steps",
                             "chairlift version", "host os image and version"]
    catalog["feature_fields"] = ["problem to solve", "proposed outcome"]
    for reader in ("bug", "enhancement", "question", "epic"):
        catalog["labels"][reader] = {"color": "ededed", "description": "Active operational reader"}
    catalog["kind_sources"] = {"bug": "kind/bug", "enhancement": "kind/feature", "question": "kind/task", "epic": "kind/task"}
    catalog["protected_labels"] = ["kind/tech-debt", "source:agent"]
    catalog["labels"]["kind/debt"] = {"color": "fbca04", "description": "Ordinary debt classification"}
    catalog["label_aliases"]["tech-debt"] = "kind/debt"
    catalog["gate_labels"] = ["question"]
    catalog["prior_comment_markers"] = [CATALOG["comment_marker"]]
    catalog["labels"]["area/ui"] = {"color": "ededed", "description": "User interface"}
    return catalog


def release_body():
    return ("### Delivery evidence\nPackage: org.projectbluefin.ChairLift\n"
            "Version: 2.3.4\nFix revision: " + "b" * 40
            + "\nRelease/build: https://github.com/projectbluefin/chairlift/releases/tag/v2.3.4\n"
            "Verify: update the application and its image-installed helper, then repeat the failure.\n")


@pytest.mark.parametrize("stage", ["awaiting-release", "needs-verification"])
def test_human_delivery_selection_survives_bot_projection(stage):
    record = issue((stage, "kind/bug"), delivery_body())
    data = facts((event(stage, time=T0),
                  event(stage, "github-actions[bot]", "Bot", time=T2, action="unlabeled"),
                  event(stage, "github-actions[bot]", "Bot", time=T2)))
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == stage
    assert final_labels(record, result) & set(CATALOG["stages"]) == {stage}


@pytest.mark.parametrize("stage", ["awaiting-release", "needs-verification"])
def test_human_delivery_withdrawal_is_not_hidden_by_bot_projection(stage):
    record = issue((stage, "kind/bug"), delivery_body())
    data = facts((event(stage, time=T0), event(stage, action="unlabeled"),
                  event(stage, "github-actions[bot]", "Bot", time=T2)))
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "needs-triage"
    assert not result["close"]
    assert not result["notify_reporter"]


@pytest.mark.parametrize("stage", ["awaiting-release", "needs-verification"])
@pytest.mark.parametrize("edited", [T1, T2])
def test_body_edit_requires_fresh_human_delivery_selection(stage, edited):
    record = issue((stage, "kind/bug"), delivery_body())
    data = facts((event(stage), event(stage, "github-actions[bot]", "Bot", time=T2)), edited=edited)
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "needs-triage"
    assert not result["close"]


@pytest.mark.parametrize("reset", ["needs-triage", "triage/needs-information"])
def test_assessment_reset_outweighs_delivery_projection(reset):
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts((event("needs-verification", time=T0),
                  event(reset, "github-actions[bot]", "Bot"),
                  event("needs-verification", "github-actions[bot]", "Bot", time=T2)))
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] != "needs-verification"
    assert not result["close"]


def test_verification_reply_anchors_human_request_not_later_bot_projection():
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts((event("needs-verification", time=T0),
                  event("needs-verification", "github-actions[bot]", "Bot", time=T2)),
                 (reply("Confirmed fixed in the published version", time=T1),))
    assert policy.plan(record, data, CATALOG)["close"]


def test_negative_reply_before_bot_projection_returns_to_triage():
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts((event("needs-verification", time=T0),
                  event("needs-verification", "github-actions[bot]", "Bot", time=T2)),
                 (reply("Still broken on the published version", time=T1),))
    result = policy.plan(record, data, CATALOG)
    assert result["stage"] == "needs-triage"
    assert not result["close"]


def test_release_delivery_requires_package_version_and_ordinary_reporter_confirmation():
    catalog = release_catalog()
    record = issue(("needs-verification", "kind/bug"), release_body())
    data = facts((event("needs-verification"),))
    result = policy.plan(record, data, catalog)
    assert result["stage"] == "needs-verification"
    assert result["notify_reporter"]
    assert "2.3.4" in result["comment"]
    assert "image-installed helper" in result["comment"]
    data["comments"].append(reply("Confirmed fixed in 2.3.4"))
    assert policy.plan(record, data, catalog)["close"]
    record["body"] = release_body().replace("Version: 2.3.4\n", "")
    result = policy.plan(record, data, catalog)
    assert result["stage"] == "awaiting-release"
    assert not result["close"]
    assert not result["notify_reporter"]


def test_image_receipt_cannot_substitute_for_application_release():
    catalog = release_catalog()
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    assert policy.plan(record, facts((event("needs-verification"),)), catalog)["stage"] == "awaiting-release"


def test_application_intake_requires_its_own_fields_not_common_image_details():
    record = issue(body="### What happened?\nBroken\n### Expected behavior\nWorks\n"
                   "### Reproduction steps\nLaunch\n### ChairLift version\n2.3.4\n"
                   "### Host OS image and version\nBluefin latest\n")
    result = policy.plan(record, facts(), release_catalog())
    assert result["stage"] == "needs-triage"
    assert final_labels(record, result) == {"kind/bug", "needs-triage", "needs-human"}
    assert not result["notify_reporter"]


@pytest.mark.parametrize("legacy,canonical", [("bug", "kind/bug"), ("enhancement", "kind/feature"), ("question", "kind/task")])
def test_source_backed_reader_label_survives_kind_normalization(legacy, canonical):
    result = policy.plan(issue((legacy,)), facts(), release_catalog(), migrate=True)
    assert final_labels(issue((legacy,)), result) == {legacy, canonical, "needs-triage", "needs-human"}


@pytest.mark.parametrize("state,is_pr", [("open", False), ("closed", False), ("open", True), ("closed", True)])
def test_explicit_alias_migration_includes_closed_history_and_prs(state, is_pr):
    catalog = release_catalog()
    catalog["label_aliases"] = {"old-bug": "kind/bug", "old-ui": "area/ui", "discard-old": None}
    record = issue(("old-bug", "old-ui", "discard-old", "1-triage", "hold", "agent/security", "hive/route"))
    record["state"] = state
    if is_pr:
        record["pull_request"] = {}
        record["labels"].append("needs-triage")
    result = policy.plan(record, facts(), catalog, migrate=True)
    final = final_labels(record, result)
    assert {"kind/bug", "area/ui", "hold", "agent/security", "hive/route"} <= final
    assert not final & {"old-bug", "old-ui", "discard-old", "1-triage"}
    assert not result["comment"] and not result["close"] and not result["notify_reporter"]
    if is_pr:
        assert not final & set(catalog["stages"])


@pytest.mark.parametrize("target", ["triage/accepted", "needs-human", "human-only"])
def test_alias_cannot_mint_consent_or_change_an_independent_gate(target):
    catalog = release_catalog()
    catalog["label_aliases"] = {"old-queue": target}
    with pytest.raises(ValueError, match="Aliases"):
        policy.plan(issue(("old-queue",)), facts(), catalog, migrate=True)


def test_ambiguous_kind_preserves_descriptors_and_requires_classification():
    record, data = accepted()
    record["labels"].append("kind/bug")
    result = policy.plan(record, data, CATALOG)
    assert {"kind/bug", "kind/feature"} <= final_labels(record, result)
    assert {"needs-kind", "needs-human"} <= final_labels(record, result)
    record["labels"] = sorted(final_labels(record, result))
    repeated = policy.plan(record, data, CATALOG)
    assert {"kind/bug", "kind/feature", "needs-kind", "needs-human"} <= final_labels(record, repeated)


def test_trusted_human_kind_choice_resolves_conflict_without_revoking_scope():
    record, data = accepted()
    record["labels"].append("kind/bug")
    data["timeline"].append(event("kind/bug", time=T2))
    result = policy.plan(record, data, CATALOG)
    assert final_labels(record, result) == {"triage/accepted", "kind/bug"}


@pytest.mark.parametrize("repository", ["projectbluefin/common", "projectbluefin/chairlift"])
def test_reference_extraction_is_catalog_bound(repository):
    other = "projectbluefin/chairlift" if repository.endswith("common") else "projectbluefin/common"
    assert policy.referenced_issues(f"Refs #10\nFixes {repository}#11\nRefs https://github.com/{repository}/issues/12\nCloses {other}#10", repository) == {10, 11, 12}


@pytest.mark.parametrize("path", ["repos/projectbluefin/common/issues/10/labels", "repos/projectbluefin/chairlift/../common/issues/10/labels", "repos/projectbluefin/chairlift/%2e%2e/common/issues/10/labels", "https://api.github.com/repos/projectbluefin/common/issues/10/labels"])
def test_release_client_refuses_escape_paths_before_network(path):
    catalog = release_catalog()
    client = policy.GitHub(catalog["repository"], catalog)
    client.writes_authorized = True
    with pytest.raises(ValueError, match="Write outside"):
        client.request("POST", path, {"labels": ["kind/bug"]})


def test_valid_scoped_write_still_requires_deployed_source_authorization():
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    with pytest.raises(RuntimeError, match="Writes require"):
        client.request("POST", "repos/projectbluefin/common/issues/10/labels", {"labels": ["needs-triage"]})


@pytest.mark.parametrize("query", ["mutation { deleteIssue }", "# note\nmutation { deleteIssue }", "query Read { viewer { login } } mutation Write { deleteIssue }"])
def test_graphql_cannot_escape_write_authorization(query):
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    with pytest.raises(ValueError, match="mutations"):
        client.request("POST", "graphql", {"query": query})


def test_release_collection_scopes_graphql_to_configured_repository(monkeypatch):
    catalog = release_catalog()
    record = issue(("kind/bug",))
    record["html_url"] = "https://github.com/projectbluefin/chairlift/issues/10"
    client = policy.GitHub(catalog["repository"], catalog)
    queries = []
    def request(method, path, body=None, **kwargs):
        if path == "graphql":
            queries.append(body)
            return {"data": {"repository": {"issue": {"lastEditedAt": None}}}}
        if path.endswith("issues/10"):
            return record
        return []
    monkeypatch.setattr(client, "request", request)
    collected, data = client.collect(10)
    assert collected is record
    assert queries[0]["variables"] == {"owner": "projectbluefin", "name": "chairlift", "number": 10}
    assert policy.plan(collected, data, catalog)["stage"] == "needs-triage"


@pytest.mark.parametrize("catalog_factory", [lambda: copy.deepcopy(CATALOG), release_catalog])
def test_real_cli_reads_either_catalog_and_snapshot_without_live_writes(tmp_path, catalog_factory):
    catalog = catalog_factory()
    catalog_path = tmp_path / "policy.json"
    catalog_path.write_text(json.dumps(catalog))
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps([{"record": issue(("kind/bug",)), "facts": facts()}]))
    output = tmp_path / "preview.json"
    assert policy.main(["--catalog", str(catalog_path), "--snapshot", str(snapshot), "--output", str(output)]) == 0
    proposed = json.loads(output.read_text())[0]["plan"]
    assert proposed["stage"] == "needs-triage"
    assert not proposed["close"]


def test_notification_dedup_ignores_markdown_and_bot_projection(monkeypatch):
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    record["html_url"] = "https://github.com/projectbluefin/common/issues/10"
    data = facts((event("needs-verification", time=T0),))
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    posted = []
    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return record
        if method == "POST" and path.endswith("/comments"):
            comment = reply(body["body"], actor="github-actions[bot]", kind="Bot")
            comment["id"] = len(posted) + 10
            posted.append(comment)
            data["comments"].append(comment)
        if method == "PATCH" and "/comments/" in path:
            for comment in data["comments"]:
                if path.endswith("/" + str(comment["id"])):
                    comment["body"] = body["body"]
    monkeypatch.setattr(client, "request", request)
    result = policy.plan(record, data, CATALOG)
    client.apply(record, data, result)
    data["timeline"].append(event("needs-verification", "github-actions[bot]", "Bot", time=T2))
    revised = policy.plan(record, data, CATALOG)
    revised["comment"] += "\nNew formatting, same authorized action."
    client.apply(record, data, revised)
    assert len(posted) == 1
    assert "@reporter" in posted[0]["body"]
    assert revised["request_id"] == result["request_id"]


def trusted_source_fixture(tmp_path, monkeypatch, catalog=None):
    import base64
    catalog = catalog or copy.deepcopy(CATALOG)
    catalog["main_ci_workflows"] = [".github/workflows/unit-tests.yml"]
    workspace = tmp_path / "caller"
    directory = workspace / ".github/workflows"
    directory.mkdir(parents=True)
    catalog_path = workspace / ".github/issue-policy.json"
    catalog_path.write_text(json.dumps(catalog))
    workflow = directory / "issue-lifecycle.yml"
    workflow.write_text("name: reviewed caller\n")
    caller_sha, action_sha = "a" * 40, "b" * 40
    environment = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": catalog["repository"],
        "ISSUE_POLICY_ACTION_REPOSITORY": policy.ACTION_REPOSITORY,
        "ISSUE_POLICY_ACTION_REF": "v1", "GH_TOKEN": "workflow-token",
        "ISSUE_POLICY_WORKFLOW_TOKEN": "workflow-token",
        "GITHUB_WORKFLOW_REF": catalog["repository"] + "/.github/workflows/issue-lifecycle.yml@refs/heads/main",
        "GITHUB_WORKFLOW_SHA": caller_sha,
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    responses = {
        f"repos/{catalog['repository']}": {"default_branch": "main"},
        f"repos/{catalog['repository']}/commits/main": {"sha": caller_sha},
        f"repos/{catalog['repository']}/compare/{caller_sha}...{caller_sha}": {"status": "identical"},
        f"repos/{policy.ACTION_REPOSITORY}": {"default_branch": "main"},
        f"repos/{policy.ACTION_REPOSITORY}/commits/v1": {"sha": action_sha},
        f"repos/{policy.ACTION_REPOSITORY}/commits/main": {"sha": action_sha},
        f"repos/{policy.ACTION_REPOSITORY}/compare/{action_sha}...{action_sha}": {"status": "identical"},
    }
    for repo, sha, workflows in (
        (catalog["repository"], caller_sha, catalog["main_ci_workflows"]),
        (policy.ACTION_REPOSITORY, action_sha, [".github/workflows/unit-tests.yml", ".github/workflows/actionlint.yml"]),
    ):
        for ci in workflows:
            responses[f"repos/{repo}/actions/workflows/{ci.rsplit('/', 1)[-1]}/runs?head_sha={sha}&branch=main&per_page=100"] = {
                "workflow_runs": [{"id": 1, "run_attempt": 1, "head_sha": sha, "head_branch": "main",
                                   "event": "push", "status": "completed", "conclusion": "success"}]}
    for relative in (".github/issue-policy.json", ".github/workflows/issue-lifecycle.yml"):
        responses[f"repos/{catalog['repository']}/contents/{relative}?ref={caller_sha}"] = {
            "encoding": "base64", "content": base64.b64encode((workspace / relative).read_bytes()).decode(),
        }
    for relative in policy.SOURCE_FILES:
        responses[f"repos/{policy.ACTION_REPOSITORY}/contents/{relative}?ref={action_sha}"] = {
            "encoding": "base64", "content": base64.b64encode((ROOT / relative).read_bytes()).decode(),
        }
    client = policy.GitHub(catalog["repository"], catalog)
    monkeypatch.setattr(client, "request", lambda method, path, body=None, **kwargs: responses[path])
    return client, catalog_path, workspace, responses


@pytest.mark.parametrize("catalog_factory", [lambda: copy.deepcopy(CATALOG), release_catalog])
def test_reviewed_default_branch_source_authorizes_each_catalog(tmp_path, monkeypatch, catalog_factory):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch, catalog_factory())
    client.require_deployed_policy(path, workspace)
    assert client.writes_authorized


@pytest.mark.parametrize("key,value", [("GITHUB_WORKFLOW_REF", "projectbluefin/common/.github/workflows/issue-lifecycle.yml@refs/heads/feature"), ("ISSUE_POLICY_ACTION_REF", "feature"), ("ISSUE_POLICY_ACTION_REPOSITORY", "outsider/actions"), ("GH_TOKEN", "local-user-token")])
def test_untrusted_workflow_action_or_token_never_authorizes_writes(tmp_path, monkeypatch, key, value):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        client.require_deployed_policy(path, workspace)
    assert not client.writes_authorized


@pytest.mark.parametrize("changed", ["catalog", "workflow", "runtime", "renderer", "composite", "ancestry"])
def test_unmerged_or_changed_source_never_authorizes_writes(tmp_path, monkeypatch, changed):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    if changed == "catalog":
        path.write_text(path.read_text() + "\n")
    elif changed == "workflow":
        (workspace / ".github/workflows/issue-lifecycle.yml").write_text("unmerged workflow")
    elif changed == "ancestry":
        responses[f"repos/{policy.ACTION_REPOSITORY}/compare/{'b' * 40}...{'b' * 40}"] = {"status": "divergent"}
    else:
        relative = {"runtime": "scripts/issue_policy.py", "renderer": "scripts/issue_status.py", "composite": "issue-lifecycle/action.yml"}[changed]
        responses[f"repos/{policy.ACTION_REPOSITORY}/contents/{relative}?ref={'b' * 40}"]["content"] = "dW5tZXJnZWQ="
    with pytest.raises(RuntimeError):
        client.require_deployed_policy(path, workspace)
    assert not client.writes_authorized


def test_migration_archives_all_history_before_mutating_aliases(tmp_path, monkeypatch):
    catalog = release_catalog()
    catalog["label_aliases"] = {"old-bug": "kind/bug"}
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog))
    records = [issue(("old-bug",), number=10), issue(("old-bug",), number=11)]
    records[1]["state"] = "closed"
    records[1]["pull_request"] = {}
    unchanged = issue(("kind/bug", "hold"), number=12)
    unchanged.update(state="closed", pull_request={})
    records.append(unchanged)
    backups = tmp_path / "backups"
    writes = []
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(policy.GitHub, "require_deployed_policy", lambda *args, **kwargs: None)
    monkeypatch.setattr(policy.GitHub, "sync_catalog", lambda *args: None)
    monkeypatch.setattr(policy.GitHub, "collect", lambda self, number, **kwargs: (next(r for r in records if r["number"] == number), facts()))
    def request(self, method, path, body=None, **kwargs):
        assert method == "GET"
        return records if "/issues?" in path else [{"name": "old-bug"}]
    monkeypatch.setattr(policy.GitHub, "request", request)
    def apply(self, record, data, result):
        archives = list(backups.rglob("*.json"))
        assert len(archives) == 1
        archive = json.loads(archives[0].read_text())
        assert archive["repository"] == catalog["repository"]
        assert len(archive["issues"]) == 3
        assert archive["labels"] == [{"name": "old-bug"}]
        writes.append(result)
    monkeypatch.setattr(policy.GitHub, "apply", apply)
    assert policy.main(["--catalog", str(catalog_path), "--backup-dir", str(backups), "--migrate", "--apply"]) == 0
    assert len(writes) == 2
    assert all("old-bug" in result["remove"] for result in writes)


def test_retirement_checks_closed_history_and_pr_assignments(tmp_path, monkeypatch):
    catalog = release_catalog()
    catalog["label_aliases"] = {"old-bug": "kind/bug"}
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog))
    historical = issue(("old-bug",), number=11)
    historical["state"] = "closed"
    historical["pull_request"] = {}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(policy.GitHub, "require_deployed_policy", lambda *args, **kwargs: None)
    monkeypatch.setattr(policy.GitHub, "sync_catalog", lambda *args: None)
    monkeypatch.setattr(policy.GitHub, "collect", lambda *args, **kwargs: (historical, facts()))
    monkeypatch.setattr(policy.GitHub, "apply", lambda *args: None)
    queried = []
    def request(self, method, path, body=None, **kwargs):
        assert method == "GET", "Definitions cannot be deleted while historical assignments remain"
        queried.append(path)
        return [historical] if "/issues?" in path else [{"name": "old-bug"}]
    monkeypatch.setattr(policy.GitHub, "request", request)
    with pytest.raises(RuntimeError, match="assignments remain"):
        policy.main(["--catalog", str(catalog_path), "--backup-dir", str(tmp_path / "backup"), "--retire-labels", "--confirm-client-cutover", "--apply"])
    assert all("state=all" in path for path in queried if "/issues?" in path)


def test_native_reader_gate_is_not_cleared_by_acceptance_or_bot_gate_provenance():
    catalog = release_catalog()
    record, data = accepted(("question", "needs-human"))
    data["timeline"].insert(0, event("needs-human", "github-actions[bot]", "Bot", time=T0))
    result = policy.plan(record, data, catalog)
    assert result["stage"] == "triage/accepted"
    assert {"question", "needs-human"} <= final_labels(record, result)
    assert "question" in result["comment"]
    assert not result["notify_reporter"]


def test_operational_kind_sources_do_not_override_existing_canonical_kind():
    catalog = release_catalog()
    record = issue(("question", "kind/bug"))
    result = policy.plan(record, facts(), catalog)
    assert "kind/task" not in final_labels(record, result)
    assert {"kind/bug", "question", "needs-human"} <= final_labels(record, result)


def test_conflicting_operational_kind_sources_preserve_readers_until_classified():
    catalog = release_catalog()
    record = issue(("bug", "enhancement"))
    result = policy.plan(record, facts(), catalog)
    assert {"bug", "enhancement", "needs-kind", "needs-human"} <= final_labels(record, result)
    assert not any(label.startswith("kind/") for label in final_labels(record, result))


def test_existing_epic_reader_is_a_standing_tracker_without_positive_dispatch():
    record = issue(("epic",))
    result = policy.plan(record, facts(), release_catalog())
    assert {"epic", "kind/task", "tracking", "needs-human", "needs-triage"} <= final_labels(record, result)


@pytest.mark.parametrize("kind,user", [("Bot", "github-actions[bot]"), ("User", "reporter"), ("Bot", "other[bot]")])
def test_transferred_common_status_reuses_only_authorized_machine_comment(monkeypatch, kind, user):
    catalog = release_catalog()
    record = issue(("needs-triage", "kind/bug"))
    record["html_url"] = "https://github.com/projectbluefin/chairlift/issues/10"
    old = reply(CATALOG["comment_marker"] + "\nObsolete Common status", actor=user, kind=kind)
    old["id"] = 7
    original = old["body"]
    data = facts(comments=(old,))
    client = policy.GitHub(catalog["repository"], catalog)
    posted, patched = [], []
    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return record
        if method == "PATCH" and path.endswith("/comments/7"):
            old["body"] = body["body"]
            patched.append(path)
        if method == "POST" and path.endswith("/comments"):
            posted.append(body["body"])
    monkeypatch.setattr(client, "request", request)
    client.apply(record, data, policy.plan(record, data, catalog))
    if kind == "Bot" and user == "github-actions[bot]":
        assert old["body"].startswith(catalog["comment_marker"])
        assert len(patched) == 1
        assert not posted
    else:
        assert old["body"] == original
        assert not patched
        assert len(posted) == 1


def test_multiple_machine_statuses_collapse_to_one_active_report_and_preserved_history(monkeypatch):
    catalog = release_catalog()
    record = issue(("needs-triage", "kind/bug"))
    record["html_url"] = "https://github.com/projectbluefin/chairlift/issues/10"
    old = reply(CATALOG["comment_marker"] + "\nObsolete Common status", actor="github-actions[bot]", kind="Bot")
    current = reply(catalog["comment_marker"] + "\nCurrent ChairLift status", actor="github-actions[bot]", kind="Bot")
    old["id"], current["id"] = 7, 8
    original = old["body"]
    data = facts(comments=(old, current))
    client = policy.GitHub(catalog["repository"], catalog)
    posted = []
    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return record
        if method == "PATCH":
            for comment in data["comments"]:
                if path.endswith("/comments/" + str(comment["id"])):
                    comment["body"] = body["body"]
        if method == "POST" and path.endswith("/comments"):
            posted.append(body["body"])
    monkeypatch.setattr(client, "request", request)
    client.apply(record, data, policy.plan(record, data, catalog))
    assert not posted
    assert current["body"].startswith(catalog["comment_marker"])
    assert old["body"].startswith("**Archived automated status:**")
    assert original in old["body"]
    assert "<details>" in old["body"]


@pytest.mark.parametrize("state,is_pr", [("closed", False), ("open", True), ("closed", True)])
@pytest.mark.parametrize("reader,kind", [("bug", "kind/bug"), ("enhancement", "kind/feature"), ("question", "kind/task")])
def test_operational_reader_kind_migration_includes_closed_issues_and_prs(state, is_pr, reader, kind):
    record = issue((reader, "hold", "agent/security"))
    record["state"] = state
    if is_pr:
        record["pull_request"] = {}
        record["labels"].append("needs-triage")
    result = policy.plan(record, facts(), release_catalog(), migrate=True)
    assert {reader, kind, "hold", "agent/security"} <= final_labels(record, result)
    assert result["stage"] is None
    assert not result["comment"] and not result["close"] and not result["notify_reporter"]
    if is_pr:
        assert not final_labels(record, result) & policy.STAGES


@pytest.mark.parametrize("field,value", [
    ("kind_sources", {"question": "triage/accepted"}),
    ("kind_sources", {"unknown-reader": "kind/bug"}),
    ("gate_labels", ["undefined-gate"]),
    ("prior_comment_markers", ["not-a-hidden-marker"]),
])
def test_optional_reader_and_marker_data_are_validated_before_planning(field, value):
    catalog = release_catalog()
    catalog[field] = value
    with pytest.raises(ValueError):
        policy.plan(issue(("question",)), facts(), catalog)


@pytest.mark.parametrize("labels", [("kind/custom",), ("kind/custom", "kind/feature")])
def test_unknown_kind_is_preserved_and_cannot_release_acceptance_gate(labels):
    record = issue(("triage/accepted", "needs-human", *labels), "### What happened?\nBroken\n")
    data = facts((event("triage/accepted"), event("needs-human", "github-actions[bot]", "Bot")))
    result = policy.plan(record, data, CATALOG)
    assert {"kind/custom", "needs-kind", "needs-human"} <= final_labels(record, result)
    assert not result["close"]


@pytest.mark.parametrize("conclusion", [None, "failure", "cancelled", "skipped"])
def test_main_ci_not_successful_never_authorizes_writes(tmp_path, monkeypatch, conclusion):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    key = f"repos/{client.repo}/actions/workflows/unit-tests.yml/runs?head_sha={'a' * 40}&branch=main&per_page=100"
    responses[key]["workflow_runs"][0]["conclusion"] = conclusion
    with pytest.raises(RuntimeError, match="successful main CI"):
        client.require_deployed_policy(path, workspace)
    assert not client.writes_authorized


def test_missing_main_ci_never_authorizes_writes(tmp_path, monkeypatch):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    key = f"repos/{client.repo}/actions/workflows/unit-tests.yml/runs?head_sha={'a' * 40}&branch=main&per_page=100"
    responses[key]["workflow_runs"] = []
    with pytest.raises(RuntimeError, match="successful main CI"):
        client.require_deployed_policy(path, workspace)
    assert not client.writes_authorized


def _main_ci_key(client):
    return f"repos/{client.repo}/actions/workflows/unit-tests.yml/runs?head_sha={'a' * 40}&branch=main&per_page=100"


def _fake_clock(monkeypatch, on_sleep=None):
    clock = {"now": 0.0, "sleeps": []}

    def sleep(seconds):
        clock["sleeps"].append(seconds)
        clock["now"] += seconds
        if on_sleep:
            on_sleep(clock)

    monkeypatch.setattr(policy.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(policy.time, "sleep", sleep)
    return clock


def _main_args(path, workspace, *extra):
    return ["--catalog", str(path), "--workspace", str(workspace), "--apply", *extra]


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting"])
def test_pending_main_ci_is_not_authorization_and_is_distinct_from_failure(tmp_path, monkeypatch, status):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    responses[_main_ci_key(client)]["workflow_runs"][0].update(status=status, conclusion=None)
    with pytest.raises(policy.MainCIPending, match="still running"):
        client.require_deployed_policy(path, workspace)
    assert not client.writes_authorized


def test_main_ci_finishing_within_the_wait_authorizes_writes(tmp_path, monkeypatch):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    run = responses[_main_ci_key(client)]["workflow_runs"][0]
    run.update(status="in_progress", conclusion=None)

    def finish(clock):
        if len(clock["sleeps"]) == 2:
            run.update(status="completed", conclusion="success")

    clock = _fake_clock(monkeypatch, finish)
    client.require_deployed_policy(path, workspace, main_ci_wait=600)
    assert client.writes_authorized
    assert clock["sleeps"] == [policy.MAIN_CI_POLL_SECONDS] * 2


def test_main_ci_failing_within_the_wait_still_fails_closed(tmp_path, monkeypatch):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    run = responses[_main_ci_key(client)]["workflow_runs"][0]
    run.update(status="in_progress", conclusion=None)
    _fake_clock(monkeypatch, lambda clock: run.update(status="completed", conclusion="failure"))
    with pytest.raises(RuntimeError, match="successful main CI") as raised:
        client.require_deployed_policy(path, workspace, main_ci_wait=600)
    assert not isinstance(raised.value, policy.MainCIPending)
    assert not client.writes_authorized


def test_reconcile_defers_without_writes_when_main_ci_outlasts_the_wait(tmp_path, monkeypatch, capsys):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    responses[_main_ci_key(client)]["workflow_runs"][0].update(status="in_progress", conclusion=None)
    requested = []

    def request(self, method, api_path, body=None, **kwargs):
        requested.append((method, api_path))
        return responses[api_path]

    monkeypatch.setattr(policy.GitHub, "request", request)
    clock = _fake_clock(monkeypatch)
    assert policy.main(_main_args(path, workspace)) == 0
    assert clock["now"] >= policy.MAIN_CI_WAIT_SECONDS
    assert all(method == "GET" for method, _ in requested)
    assert not any("/issues" in api_path or "/labels" in api_path for _, api_path in requested)
    assert "::notice::Main CI still running" in capsys.readouterr().out


def test_authorize_only_never_waits_and_fails_closed_on_pending_main_ci(tmp_path, monkeypatch):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    responses[_main_ci_key(client)]["workflow_runs"][0].update(status="in_progress", conclusion=None)
    monkeypatch.setattr(policy.GitHub, "request", lambda self, method, api_path, body=None, **kwargs: responses[api_path])
    clock = _fake_clock(monkeypatch)
    with pytest.raises(policy.MainCIPending):
        policy.main(_main_args(path, workspace, "--authorize-only"))
    assert clock["sleeps"] == []


def test_failed_notice_post_does_not_mark_request_delivered(monkeypatch):
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    record["html_url"] = "https://github.com/projectbluefin/common/issues/10"
    data = facts((event("needs-verification"),))
    previous = reply(CATALOG["comment_marker"] + "\nOld waiting status", actor="github-actions[bot]", kind="Bot")
    data["comments"] = [previous]
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    attempts = []
    posted = []
    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return record
        if method == "POST" and path.endswith("/comments"):
            attempts.append(body)
            if len(attempts) == 1:
                raise RuntimeError("notice post failed")
            notice = reply(body["body"], actor="github-actions[bot]", kind="Bot")
            notice["id"] = 99
            posted.append(notice)
            data["comments"].append(notice)
        if method == "PATCH" and "/comments/" in path:
            previous["body"] = body["body"]
    monkeypatch.setattr(client, "request", request)
    result = policy.plan(record, data, CATALOG)
    with pytest.raises(RuntimeError, match="notice post failed"):
        client.apply(record, data, result)
    assert ":request:" not in previous["body"]
    client.apply(record, data, result)
    client.apply(record, data, result)
    assert len(posted) == 1
    assert len(attempts) == 2


@pytest.mark.parametrize("action_ref,allowed", [("b" * 40, True), ("c" * 40, False)])
def test_self_composition_commit_must_equal_managed_release(tmp_path, monkeypatch, action_ref, allowed):
    client, path, workspace, responses = trusted_source_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("ISSUE_POLICY_ACTION_REF", action_ref)
    if allowed:
        client.require_deployed_policy(path, workspace)
        assert client.writes_authorized
    else:
        with pytest.raises(RuntimeError, match="managed v1 release"):
            client.require_deployed_policy(path, workspace)
        assert not client.writes_authorized


def test_application_feature_form_requests_only_its_own_required_fields():
    catalog = release_catalog()
    record = issue(("kind/feature",), "### Problem to solve\nA task is difficult\n### Proposed outcome\nMake it easier\n")
    result = policy.plan(record, facts(), catalog)
    assert result["stage"] == "needs-triage"
    assert not result["notify_reporter"]
    record["body"] = "### Problem to solve\nA task is difficult\n### Proposed outcome\n_No response_\n"
    result = policy.plan(record, facts(), catalog)
    assert result["stage"] == "triage/needs-information"
    assert result["notify_reporter"]
    assert "proposed outcome" in result["comment"]
    assert "desired outcome" not in result["comment"]
    assert "affected component" not in result["comment"]


@pytest.mark.parametrize("state,is_pr", [("closed", False), ("closed", True), ("open", True)])
def test_quiet_historical_collection_uses_live_listing_without_authority_reads(monkeypatch, state, is_pr):
    record = issue(("1-triage", "kind/feature", "hold"))
    record.update(state=state, html_url="https://github.com/projectbluefin/common/issues/10")
    if is_pr:
        record["pull_request"] = {}
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    def unnecessary_read(*args, **kwargs):
        raise AssertionError("quiet historical label cleanup must not request grant or native PR facts")
    monkeypatch.setattr(client, "request", unnecessary_read)
    collected, data = client.collect(10, record=record, quiet=True)
    result = policy.plan(collected, data, CATALOG, migrate=True)
    assert "1-triage" in result["remove"]
    assert "hold" not in result["remove"]
    assert result["comment"] is None and not result["notify_reporter"] and not result["close"]


def test_quiet_open_issue_still_reads_authorized_scope_history(monkeypatch):
    record = issue(("kind/feature",))
    record["html_url"] = "https://github.com/projectbluefin/common/issues/10"
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    paths = []
    def request(method, path, body=None, **kwargs):
        paths.append(path)
        if path == "graphql":
            return {"data": {"repository": {"issue": {"lastEditedAt": None}}}}
        return []
    monkeypatch.setattr(client, "request", request)
    collected, data = client.collect(10, record=record, quiet=True)
    assert any("/timeline" in path for path in paths)
    assert "graphql" in paths
    assert data["last_edited_at"] is None


def test_retirement_preview_cannot_request_action_or_close_verified_issue(tmp_path):
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    data = facts((event("needs-verification"),), comments=(reply("Confirmed fixed"),))
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(CATALOG))
    snapshot_path = tmp_path / "history.json"
    snapshot_path.write_text(json.dumps([{"record": record, "facts": data}]))
    output_path = tmp_path / "retirement.json"
    assert policy.main(["--catalog", str(catalog_path), "--snapshot", str(snapshot_path),
                        "--retire-labels", "--dry-run", "--output", str(output_path)]) == 0
    result = json.loads(output_path.read_text())[0]["plan"]
    assert result["comment"] is None
    assert not result["notify_reporter"]
    assert not result["close"]


def metadata_intake_catalog():
    catalog = copy.deepcopy(CATALOG)
    for label in ("area/runtime", "agent/quality"):
        catalog["labels"][label] = {"color": "ededed", "description": "Descriptive intake metadata"}
    catalog["intake_rules"] = [{"match": {"title_prefixes": ["APP:"], "body_contains": ["intake marker"]},
                               "labels": ["kind/task", "area/runtime", "agent/quality"]}]
    return catalog


def test_catalog_intake_metadata_never_accepts_assigns_or_infers_consent():
    catalog = metadata_intake_catalog()
    record = issue(body="intake marker\n### Automation preference\nHuman interaction only\n")
    record.update(title="app: specific task", assignees=[{"login": "existing-owner"}])
    result = policy.plan(record, facts(), catalog)
    assert {"kind/task", "area/runtime", "agent/quality", "needs-triage", "needs-human", "human-only"} <= final_labels(record, result)
    assert result["stage"] != "triage/accepted"
    assert record["assignees"] == [{"login": "existing-owner"}]
    assert not result["notify_reporter"] and not result["close"]
    record["body"] = "intake marker"
    assert "human-only" not in final_labels(record, policy.plan(record, facts(), catalog))


def test_intake_rules_require_all_groups_and_preserve_existing_primary_kind():
    catalog = metadata_intake_catalog()
    record = issue(("kind/feature", "hold", "needs-human"), "intake marker")
    record["title"] = "APP: classified feature"
    result = policy.plan(record, facts(), catalog)
    assert "kind/task" not in final_labels(record, result)
    assert {"kind/feature", "area/runtime", "hold", "needs-human"} <= final_labels(record, result)
    record["title"] = "unmatched title"
    assert "area/runtime" not in final_labels(record, policy.plan(record, facts(), catalog))


@pytest.mark.parametrize("target", ["triage/accepted", "human-only", "needs-human", "hold", "blocked", "tracking", "lgtm", "automerge", "ai-fix-requested", "hive/ready", "undefined"])
def test_intake_rules_reject_unsupported_or_control_targets(target):
    catalog = metadata_intake_catalog()
    if target not in catalog["stages"] and target != "undefined":
        catalog["labels"][target] = {"color": "ededed", "description": "Protected control"}
    catalog["intake_rules"][0]["labels"] = [target]
    with pytest.raises(ValueError, match="Intake targets"):
        policy.plan(issue(), facts(), catalog)


def test_consumer_without_intake_rules_does_not_inherit_another_apps_profile():
    record = issue(body="Filed by guide agent")
    record["title"] = "[guide] Documentation task"
    result = policy.plan(record, facts(), CATALOG)
    assert final_labels(record, result) == {"needs-triage", "needs-human", "needs-kind"}


def test_bounded_intake_does_not_match_body_marker_outside_reviewed_window():
    catalog = metadata_intake_catalog()
    record = issue(body="x" * 65536 + "intake marker")
    record["title"] = "APP: oversized report"
    result = policy.plan(record, facts(), catalog)
    assert "agent/quality" not in final_labels(record, result)
    assert "needs-kind" in final_labels(record, result)


def test_conflicting_intake_rule_kinds_remain_gated_for_human_classification():
    catalog = metadata_intake_catalog()
    catalog["intake_rules"].append({"match": {"body_headings": ["Feature Request"]}, "labels": ["kind/feature"]})
    record = issue(body="intake marker\n## Feature Request\nA requested outcome\n")
    record["title"] = "APP: conflicting intake"
    result = policy.plan(record, facts(), catalog)
    assert {"kind/task", "kind/feature", "needs-kind", "needs-human"} <= final_labels(record, result)


@pytest.mark.parametrize("rule", [
    {"match": {"body_regex": [".*"]}, "labels": ["kind/task"]},
    {"match": {}, "labels": ["kind/task"]},
    {"match": {"title_prefixes": ["APP:"]}, "labels": ["kind/task"], "assign": ["owner"]},
    {"match": {"title_prefixes": [0]}, "labels": ["kind/task"]},
    {"match": {"body_contains": ["x" * 257]}, "labels": ["kind/task"]},
])
def test_intake_rules_reject_executable_unbounded_or_assignment_configuration(rule):
    catalog = metadata_intake_catalog()
    catalog["intake_rules"] = [rule]
    with pytest.raises(ValueError):
        policy.plan(issue(), facts(), catalog)


def test_descriptive_intake_cannot_recreate_a_resolved_native_question_gate():
    catalog = release_catalog()
    catalog["intake_rules"] = [{"match": {"title_prefixes": ["question:"]}, "labels": ["kind/task"]}]
    record = issue(("triage/accepted", "kind/task", "question", "needs-human"))
    record["title"] = "question: a resolved concern"
    data = facts((event("triage/accepted", time=T0), event("question", time=T0),
                  event("needs-human", "github-actions[bot]", "Bot", time=T0)))
    assert "needs-human" in final_labels(record, policy.plan(record, data, catalog))
    record["labels"].remove("question")
    data["timeline"].extend((event("question", action="unlabeled"),
                             event("triage/accepted", action="unlabeled"),
                             event("triage/accepted", time=T2)))
    result = policy.plan(record, data, catalog)
    assert "question" not in final_labels(record, result)
    assert "needs-human" not in final_labels(record, result)
    record["labels"] = sorted(final_labels(record, result))
    data["timeline"].append(event("needs-human", "github-actions[bot]", "Bot", time=T2, action="unlabeled"))
    settled = policy.plan(record, data, catalog)
    assert settled["add"] == [] and settled["remove"] == []
    assert settled["stage"] == "triage/accepted"
    assert settled["comment"] == result["comment"]
    assert not settled["notify_reporter"]
    catalog["intake_rules"][0]["labels"].append("question")
    with pytest.raises(ValueError, match="Intake targets"):
        policy.plan(record, data, catalog)


def test_quoted_bot_feedback_marker_cannot_claim_delivered_notification(monkeypatch):
    import hashlib
    record = issue(("needs-verification", "kind/bug"), delivery_body())
    record["html_url"] = "https://github.com/projectbluefin/common/issues/10"
    data = facts((event("needs-verification"),))
    result = policy.plan(record, data, CATALOG)
    key = hashlib.sha256(json.dumps({"repository": CATALOG["repository"], "number": 10,
                                    "request": result["request_id"], "action": result["notification_action"]},
                                   sort_keys=True).encode()).hexdigest()
    marker = CATALOG["comment_marker"].removesuffix(" -->") + ":request:" + key + " -->"
    previous = reply(CATALOG["comment_marker"] + "\nOld status", actor="github-actions[bot]", kind="Bot")
    feedback = reply("- Command: `unsupported " + marker + "`", actor="github-actions[bot]", kind="Bot")
    feedback["id"] = 3
    data["comments"] = [previous, feedback]
    posted = []
    client = policy.GitHub(CATALOG["repository"], CATALOG)
    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return record
        if method == "POST" and path.endswith("/comments"):
            posted.append(body)
    monkeypatch.setattr(client, "request", request)
    client.apply(record, data, result)
    assert len(posted) == 1
    assert marker in posted[0]["body"].splitlines()


@pytest.mark.parametrize("state,is_pr", [("open", False), ("closed", False), ("open", True), ("closed", True)])
@pytest.mark.parametrize("existing_signals", [(), ("kind/tech-debt", "source:agent")])
def test_quiet_debt_migration_never_grants_or_removes_operational_signals(state, is_pr, existing_signals):
    catalog = release_catalog()
    record = issue(("tech-debt", "hold", "human-only", *existing_signals), "Unchanged scope")
    record.update(state=state, assignees=[{"login": "existing-owner"}])
    if is_pr:
        record["pull_request"] = {}
    original = copy.deepcopy(record)
    result = policy.plan(record, facts(), catalog, migrate=True)
    assert {"kind/debt", "hold", "human-only"} <= final_labels(record, result)
    assert final_labels(record, result) & set(catalog["protected_labels"]) == set(existing_signals)
    assert not set(result["add"] + result["remove"]) & set(catalog["protected_labels"])
    assert "tech-debt" in result["remove"]
    assert not result["comment"] and not result["notify_reporter"] and not result["close"]
    assert result["notification_action"] is None
    assert record == original


def test_operational_kind_is_not_primary_classification_or_acceptance():
    catalog = release_catalog()
    record = issue(("kind/tech-debt", "source:agent", "triage/accepted", "needs-human"))
    data = facts((event("triage/accepted"), event("needs-human", "github-actions[bot]", "Bot")))
    result = policy.plan(record, data, catalog)
    assert {"kind/tech-debt", "source:agent", "needs-kind", "needs-human"} <= final_labels(record, result)
    assert not set(result["remove"]) & set(catalog["protected_labels"])
    assert not result["notify_reporter"] and not result["close"]


def test_operational_kind_and_one_canonical_kind_are_not_ambiguous():
    catalog = release_catalog()
    record = issue(("kind/tech-debt", "source:agent", "kind/debt", "triage/accepted", "needs-human"))
    data = facts((event("triage/accepted"), event("needs-human", "github-actions[bot]", "Bot")))
    result = policy.plan(record, data, catalog)
    assert final_labels(record, result) == {"kind/tech-debt", "source:agent", "kind/debt", "triage/accepted"}
    assert result["remove"] == ["needs-human"]
    record["labels"] = sorted(final_labels(record, result))
    settled = policy.plan(record, data, catalog, labels_only=True)
    assert settled["add"] == [] and settled["remove"] == []


@pytest.mark.parametrize("gate", ["hold", "blocked", "human-only", "question"])
def test_operational_kind_preservation_does_not_clear_independent_gates(gate):
    catalog = release_catalog()
    record = issue(("kind/tech-debt", "source:agent", "kind/debt", "triage/accepted", "needs-human", gate))
    data = facts((event("triage/accepted"), event("needs-human", "github-actions[bot]", "Bot")))
    result = policy.plan(record, data, catalog)
    assert final_labels(record, result) == policy.labels_of(record)
    assert result["add"] == [] and result["remove"] == []
    assert not result["notify_reporter"] and not result["close"]


def test_human_kind_selection_removes_only_descriptors_not_protected_signal():
    catalog = release_catalog()
    record = issue(("kind/tech-debt", "source:agent", "kind/bug", "kind/debt"))
    result = policy.plan(record, facts((event("kind/debt"),)), catalog)
    assert {"kind/tech-debt", "source:agent", "kind/debt"} <= final_labels(record, result)
    assert "kind/bug" in result["remove"]
    assert "needs-kind" not in final_labels(record, result)


def test_unknown_nonoperational_kind_still_gates_classification():
    catalog = release_catalog()
    record = issue(("kind/tech-debt", "kind/debt", "kind/unknown", "triage/accepted", "needs-human"))
    data = facts((event("triage/accepted"), event("needs-human", "github-actions[bot]", "Bot")))
    result = policy.plan(record, data, catalog)
    assert {"kind/tech-debt", "kind/debt", "kind/unknown", "needs-kind", "needs-human"} <= final_labels(record, result)


def test_protected_kind_does_not_block_source_backed_or_intake_classification():
    catalog = release_catalog()
    catalog["intake_rules"] = [{"match": {"title_prefixes": ["debt:"]}, "labels": ["kind/debt"]}]
    record = issue(("kind/tech-debt", "source:agent"))
    record["title"] = "debt: ordinary cleanup"
    assert "kind/debt" in final_labels(record, policy.plan(record, facts(), catalog))
    record["title"] = "unclassified"
    record["labels"].append("bug")
    assert "kind/bug" in final_labels(record, policy.plan(record, facts(), catalog))
    record["state"] = "closed"
    assert "kind/bug" in final_labels(record, policy.plan(record, facts(), catalog, migrate=True))


@pytest.mark.parametrize("name", ["kind/tech-debt", "source:agent", "Kind/Tech-Debt", "SOURCE:AGENT"])
@pytest.mark.parametrize("direction", ["source", "target"])
def test_aliases_cannot_assign_or_retire_protected_operational_labels(name, direction):
    catalog = release_catalog()
    catalog["label_aliases"] = {name: None} if direction == "source" else {"old-debt": name}
    with pytest.raises(ValueError, match="Alias"):
        policy.plan(issue((name,)), facts(), catalog, migrate=True)


@pytest.mark.parametrize("name", ["kind/tech-debt", "source:agent"])
def test_intake_and_kind_sources_cannot_assign_protected_operational_labels(name):
    catalog = release_catalog()
    catalog["intake_rules"] = [{"match": {"title_prefixes": ["debt:"]}, "labels": [name]}]
    with pytest.raises(ValueError, match="Intake targets"):
        policy.plan(issue(), facts(), catalog)
    catalog["intake_rules"] = []
    catalog["kind_sources"]["bug"] = name
    with pytest.raises(ValueError, match="kind_sources"):
        policy.plan(issue(("bug",)), facts(), catalog)


@pytest.mark.parametrize("names", ["kind/tech-debt", [None], [""], ["kind/tech-debt", "Kind/Tech-Debt"]])
def test_protected_label_declaration_is_explicit_unique_data(names):
    catalog = release_catalog()
    catalog["protected_labels"] = names
    with pytest.raises(ValueError, match="protected_labels"):
        policy.validate_catalog(catalog)


@pytest.mark.parametrize("name", ["kind/tech-debt", "source:agent", "Kind/Tech-Debt"])
def test_protected_labels_cannot_be_catalog_synced_or_retired(name):
    catalog = release_catalog()
    catalog["labels"][name] = {"color": "ffffff", "description": "Guessed definition"}
    with pytest.raises(ValueError, match="protected_labels"):
        policy.validate_catalog(catalog)
    del catalog["labels"][name]
    catalog["retired_stages"].append(name)
    with pytest.raises(ValueError, match="Retired"):
        policy.validate_catalog(catalog)


def test_sync_catalog_leaves_protected_live_definitions_unchanged(monkeypatch):
    catalog = release_catalog()
    current = [{"name": name, **definition} for name, definition in (catalog["stages"] | catalog["labels"]).items()
               if name != "kind/debt"]
    signals = [{"name": name, "color": "123456", "description": "Operator-owned live definition"}
               for name in catalog["protected_labels"]]
    current.extend(signals)
    original = copy.deepcopy(current)
    writes = []
    client = policy.GitHub(catalog["repository"], catalog)
    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return current
        writes.append((method, path, body))
    monkeypatch.setattr(client, "request", request)
    client.sync_catalog(catalog, apply=True)
    assert writes == [("POST", f"repos/{catalog['repository']}/labels", {"name": "kind/debt", **catalog["labels"]["kind/debt"]})]
    assert current == original


def test_retirement_keeps_protected_definitions_and_historical_assignments(tmp_path, monkeypatch):
    catalog = release_catalog()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog))
    historical = issue(("kind/tech-debt", "source:agent", "kind/debt"))
    historical.update(state="closed", pull_request={})
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(policy.GitHub, "require_deployed_policy", lambda *args, **kwargs: None)
    monkeypatch.setattr(policy.GitHub, "sync_catalog", lambda *args: None)
    monkeypatch.setattr(policy.GitHub, "collect", lambda *args, **kwargs: (historical, facts()))
    writes = []
    def request(self, method, path, body=None, **kwargs):
        if method == "GET":
            return [historical] if "/issues?" in path else [{"name": name} for name in (*catalog["protected_labels"], "tech-debt")]
        writes.append((method, path, body))
    monkeypatch.setattr(policy.GitHub, "request", request)
    assert policy.main(["--catalog", str(catalog_path), "--backup-dir", str(tmp_path / "backup"),
                        "--retire-labels", "--confirm-client-cutover", "--apply"]) == 0
    assert writes == [("DELETE", f"repos/{catalog['repository']}/labels/tech-debt", None)]
    assert set(historical["labels"]) == {"kind/tech-debt", "source:agent", "kind/debt"}
