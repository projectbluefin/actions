"""Execute the shared policy and complete workflow merge paths with fixture APIs."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / ".github/actions/merge-label-guard/guard.sh"


def step(workflow, job, *, name=None, step_id=None):
    jobs = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]
    return next(s["run"] for s in jobs[job]["steps"] if
                (name is not None and s.get("name") == name) or
                (step_id is not None and s.get("id") == step_id))


@pytest.fixture
def api(tmp_path):
    config = {"labels": [[[]]], "viewer": "mergeraptor", "auto_actor": None,
              "queue_actor": None, "queued": False, "auto": False}
    executable = tmp_path / "gh"
    executable.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
root = Path(os.environ["FIXTURE_API"])
cfg = json.loads((root / "config.json").read_text())
a = sys.argv[1:]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(a) + "\\n")
if a[0] == "api" and "/labels?per_page=100" in a[1]:
    if cfg.get("label_error"):
        sys.exit(1)
    count_file = root / "label_count"
    n = int(count_file.read_text()) if count_file.exists() else 0
    count_file.write_text(str(n + 1))
    print(json.dumps(cfg["labels"][min(n, len(cfg["labels"]) - 1)]))
elif a[:2] == ["api", "graphql"]:
    query = next(x[6:] for x in a if x.startswith("query="))
    if "viewer{" in query:
        if cfg.get("ownership_error"):
            sys.exit(1)
        actor = lambda value: {"id": "ACTOR_" + value} if value else None
        print(json.dumps({"data": {"viewer": actor(cfg["viewer"]), "repository": {
            "pullRequest": {"id": "PR_node", "autoMergeRequest": {"enabledBy": actor(cfg["auto_actor"])},
                            "mergeQueueEntry": {"enqueuer": actor(cfg["queue_actor"])}}}}}))
    elif "mutation" in query:
        if cfg.get("withdraw_error") and ("disablePullRequestAutoMerge" in query or "dequeuePullRequest" in query):
            sys.exit(1)
        print('{"data": {}}')
    elif "mergeQueueEntry" in query:
        print("QUEUE_node" if cfg["queued"] else "")
    else:
        sys.exit("unexpected GraphQL query: " + query)
elif a[:2] == ["pr", "view"]:
    field = a[a.index("--json") + 1]
    print({"id": "PR_node", "state": "MERGED", "headRefOid": "qualified-sha",
           "autoMergeRequest": "true" if cfg["auto"] else "false"}[field])
elif a[:2] == ["pr", "merge"]:
    if cfg.get("retry_queue"):
        print("base branch uses a merge queue", file=sys.stderr)
        sys.exit(1)
elif a[0] == "api" and "/git/ref/heads/" in a[1]:
    print("qualified-sha")
elif a[0] == "api" and "/statuses/" in a[1]:
    print('{}')
else:
    sys.exit("unexpected gh call: " + repr(a))
''')
    executable.chmod(0o755)

    def run(script=None, **changes):
        config.update(changes)
        (tmp_path / "config.json").write_text(json.dumps(config))
        env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
               "FIXTURE_API": str(tmp_path), "GITHUB_REPOSITORY": "projectbluefin/example",
               "PR_NUMBER": "12", "GITHUB_OUTPUT": str(tmp_path / "outputs"),
               "HEAD_SHA": "qualified-sha", "MERGE_METHOD": "squash",
               "MERGE_LABEL_GUARD": str(GUARD), "PROMOTION_BRANCH": "auto/promote-testing-to-main"}
        result = subprocess.run(["bash", "-c", script] if script is not None else ["bash", str(GUARD)],
                                cwd=tmp_path, env=env, text=True, capture_output=True, check=False)
        log = tmp_path / "calls.jsonl"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return run


def merge_writes(calls):
    return [c for c in calls if c[:2] == ["pr", "merge"] or
            any("enqueuePullRequest(input:" in a for a in c)]


@pytest.mark.parametrize("label", ["hold", "do-not-merge", "do-not-merge/testing", "DO-NOT-MERGE/Release"])
@pytest.mark.parametrize("ownership", ["auto_actor", "queue_actor"])
def test_held_pr_withdraws_only_owned_enrollment(api, label, ownership):
    result, calls = api(labels=[[[{"name": label}]]], **{ownership: "mergeraptor"})
    assert result.returncode == 3, result.stderr
    assert not merge_writes(calls)
    mutation = "disablePullRequestAutoMerge" if ownership == "auto_actor" else "dequeuePullRequest"
    assert any(mutation in arg for call in calls for arg in call)


def test_held_pr_does_not_withdraw_another_actors_enrollment(api):
    result, calls = api(labels=[[[{"name": "hold"}]]], auto_actor="maintainer", queue_actor="another-app")
    assert result.returncode == 3, result.stderr
    assert not any("mutation" in arg for call in calls for arg in call)


@pytest.mark.parametrize("labels", [[[]], [[{"name": "lgtm"}, {"name": "hold/review"}, {"name": "not-do-not-merge"}]]])
def test_unheld_pr_is_allowed(api, labels):
    result, calls = api(labels=[labels])
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1


def test_label_pagination_cannot_hide_a_hold(api):
    result, _ = api(labels=[[[{"name": "lgtm"}], [{"name": "hold"}]]])
    assert result.returncode == 3, result.stderr


@pytest.mark.parametrize("changes", [{"label_error": True}, {"labels": [None]}, {"labels": [[{}]]},
                                     {"labels": [[]]}, {"labels": [[[{}]]]},
                                     {"labels": [[[{'name': 'hold'}]]], "ownership_error": True},
                                     {"labels": [[[{'name': 'hold'}]]], "auto_actor": "mergeraptor", "withdraw_error": True}])
def test_unreadable_policy_or_failed_withdrawal_fails_closed(api, changes):
    result, calls = api(**changes)
    assert result.returncode not in (0, 3), result.stderr
    assert not merge_writes(calls)


RENOVATE = "reusable-renovate-automerge.yml"
PROMOTE = "reusable-promote-squash.yml"


def enrollment(queue):
    return step(PROMOTE, "enqueue", name="Enable auto-merge or enqueue verified promotion PR").replace(
        "${{ inputs.use_merge_queue }}", str(queue).lower()).replace("${{ github.repository }}", "projectbluefin/example")


@pytest.mark.parametrize("queue", [True, False])
@pytest.mark.parametrize("label", ["hold", "do-not-merge", "do-not-merge/release"])
def test_promotion_rechecks_labels_after_enrollment_state_lookup(api, queue, label):
    result, calls = api(enrollment(queue), labels=[[[]], [[{"name": label}]]])
    assert result.returncode == 0, result.stderr
    assert not merge_writes(calls)


@pytest.mark.parametrize("queue", [True, False])
def test_unheld_promotion_keeps_existing_enrollment_behavior(api, queue):
    result, calls = api(enrollment(queue))
    assert result.returncode == 0, result.stderr
    assert len(merge_writes(calls)) == 1


@pytest.mark.parametrize("queue", [True, False])
def test_promotion_api_failure_never_enables_merge(api, queue):
    result, calls = api(enrollment(queue), label_error=True)
    assert result.returncode != 0
    assert not merge_writes(calls)


def test_renovate_merge_rechecks_labels_after_check_wait(api):
    result, calls = api(step(RENOVATE, "automerge", name="Merge PR"), labels=[[[{"name": "hold"}]]])
    assert result.returncode == 0, result.stderr
    assert not merge_writes(calls)


def test_renovate_retry_rechecks_new_hold(api):
    result, calls = api(step(RENOVATE, "automerge", name="Merge PR"),
                        labels=[[[]], [[{"name": "do-not-merge/ci"}]]], retry_queue=True)
    assert result.returncode == 0, result.stderr
    assert len(merge_writes(calls)) == 1


def test_promotion_cannot_publish_merge_enabling_validate_status_when_held(api):
    script = step(PROMOTE, "enqueue", name="Post validate status after release gate")
    script = script.replace("${{ github.repository }}", "projectbluefin/example").replace(
        "${{ github.server_url }}", "https://github.com").replace("${{ github.run_id }}", "1")
    result, calls = api(script, labels=[[[{"name": "hold"}]]])
    assert result.returncode == 0, result.stderr
    assert not any("/statuses/" in c[1] for c in calls if c[0] == "api")


@pytest.mark.parametrize("queue", [True, False])
def test_promotion_late_unreadable_label_response_fails_closed(api, queue):
    result, calls = api(enrollment(queue), labels=[[[]], None])
    assert result.returncode != 0
    assert not merge_writes(calls)


@pytest.mark.parametrize("queue", [True, False])
def test_held_already_enrolled_promotion_withdraws_owned_state(api, queue):
    result, calls = api(enrollment(queue), labels=[[[{"name": "hold"}]]],
                        queued=queue, auto=not queue,
                        queue_actor="mergeraptor" if queue else None,
                        auto_actor=None if queue else "mergeraptor")
    assert result.returncode == 0, result.stderr
    assert not merge_writes(calls)
    mutation = "dequeuePullRequest" if queue else "disablePullRequestAutoMerge"
    assert any(mutation in arg for call in calls for arg in call)
