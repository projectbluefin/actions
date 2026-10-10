"""Prow wrapper's GitHub client, step outputs and CLI scope guards.

test_prow_commands.py drives prepare/finish through a fixture client. These
tests cover the code that fixture replaces: the repository-scoped HTTP client,
label pagination, GITHUB_OUTPUT writing, and main()'s refusal to run outside
GitHub Actions or against a catalog for another repository.
"""
import base64
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError

import pytest

from scripts import prow_commands as prow
from tests.test_prow_commands import FixtureGitHub, catalog, event  # noqa: F401  (pytest fixtures)

REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def fake_urlopen(monkeypatch, responder):
    seen = []

    def _urlopen(request, timeout):
        seen.append((request, timeout))
        result = responder(request)
        if isinstance(result, BaseException):
            raise result
        return FakeResponse(json.dumps(result).encode())

    monkeypatch.setattr(prow, "urlopen", _urlopen)
    return seen


def http_error(code, body, reason="Reason"):
    return HTTPError("https://api.example/x", code, reason, {}, io.BytesIO(body))


# --- GitHub.request ---------------------------------------------------------

def test_request_is_scoped_to_the_repository_and_sends_api_headers(monkeypatch):
    seen = fake_urlopen(monkeypatch, lambda request: {"ok": True})
    api = prow.GitHub("projectbluefin/example", "tkn", api_url="https://ghe.example/api/v3/")

    assert api.request("issues/12") == {"ok": True}

    request, timeout = seen[0]
    assert request.full_url == "https://ghe.example/api/v3/repos/projectbluefin/example/issues/12"
    assert request.get_method() == "GET"
    assert request.data is None
    assert timeout == 30
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["authorization"] == "Bearer tkn"
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["x-github-api-version"] == "2022-11-28"


def test_empty_path_reads_the_repository_itself(monkeypatch):
    seen = fake_urlopen(monkeypatch, lambda request: {"default_branch": "main"})
    prow.GitHub("projectbluefin/example", "tkn").request()
    assert seen[0][0].full_url == "https://api.github.com/repos/projectbluefin/example"


def test_post_body_is_json_encoded(monkeypatch):
    seen = fake_urlopen(monkeypatch, lambda request: {"id": 1})
    prow.GitHub("projectbluefin/example", "tkn").request("issues/12/comments", method="POST", data={"body": "hi"})
    request = seen[0][0]
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"body": "hi"}


def test_http_error_carries_status_and_github_message(monkeypatch):
    fake_urlopen(monkeypatch, lambda request: http_error(403, b'{"message": "Resource not accessible"}'))
    with pytest.raises(prow.ApiError) as raised:
        prow.GitHub("projectbluefin/example", "tkn").request("collaborators/x/permission")
    assert raised.value.status == 403
    assert str(raised.value) == "GitHub GET collaborators/x/permission returned 403: Resource not accessible"


def test_http_error_with_unparseable_body_falls_back_to_reason(monkeypatch):
    fake_urlopen(monkeypatch, lambda request: http_error(502, b"<html>bad gateway</html>", reason="Bad Gateway"))
    with pytest.raises(prow.ApiError) as raised:
        prow.GitHub("projectbluefin/example", "tkn").request()
    assert raised.value.status == 502
    assert str(raised.value) == "GitHub GET repository returned 502: Bad Gateway"


@pytest.mark.parametrize("failure", [URLError("dns down"), TimeoutError("slow"), "not-json"])
def test_transport_and_decode_failures_become_api_errors_without_status(monkeypatch, failure):
    if failure == "not-json":
        monkeypatch.setattr(prow, "urlopen", lambda request, timeout: FakeResponse(b"not json"))
    else:
        fake_urlopen(monkeypatch, lambda request: failure)
    with pytest.raises(prow.ApiError) as raised:
        prow.GitHub("projectbluefin/example", "tkn").request("issues/12", method="GET")
    assert raised.value.status is None
    assert str(raised.value).startswith("GitHub GET issues/12 could not be read: ")


# --- file_json / labels -----------------------------------------------------

def test_file_json_quotes_the_ref_and_decodes_base64(monkeypatch):
    content = base64.b64encode(json.dumps({"a": 1}).encode()).decode()
    seen = fake_urlopen(monkeypatch, lambda request: {"encoding": "base64", "content": content})
    api = prow.GitHub("projectbluefin/example", "tkn")
    assert api.file_json(".github/prow.yaml", "refs/heads/a b") == {"a": 1}
    assert seen[0][0].full_url.endswith("contents/.github/prow.yaml?ref=refs%2Fheads%2Fa%20b")


@pytest.mark.parametrize("response", [
    {"encoding": "none", "content": ""},
    {"encoding": "base64"},
    {"encoding": "base64", "content": None},
    {"type": "dir"},
])
def test_file_json_refuses_non_file_responses(monkeypatch, response):
    fake_urlopen(monkeypatch, lambda request: response)
    with pytest.raises(ValueError, match="is not a readable GitHub file"):
        prow.GitHub("projectbluefin/example", "tkn").file_json(".github/prow.yaml", "a" * 40)


def test_labels_follows_full_pages_until_a_short_page(monkeypatch):
    pages = {
        1: [{"name": f"l{i}"} for i in range(100)],
        2: [{"name": f"l{i}"} for i in range(100, 200)],
        3: [{"name": "last"}],
    }

    def responder(request):
        page = int(request.full_url.rsplit("page=", 1)[1])
        return pages[page]

    seen = fake_urlopen(monkeypatch, responder)
    names = prow.GitHub("projectbluefin/example", "tkn").labels("issues/12/labels")

    assert names == {f"l{i}" for i in range(200)} | {"last"}
    assert [request.full_url.rsplit("/", 1)[1] for request, _ in seen] == [
        "labels?per_page=100&page=1",
        "labels?per_page=100&page=2",
        "labels?per_page=100&page=3",
    ]


def test_labels_stops_after_one_short_page(monkeypatch):
    seen = fake_urlopen(monkeypatch, lambda request: [{"name": "hold"}])
    assert prow.GitHub("projectbluefin/example", "tkn").labels("labels") == {"hold"}
    assert len(seen) == 1


def test_labels_exactly_one_full_page_reads_an_empty_second_page(monkeypatch):
    pages = {1: [{"name": f"l{i}"} for i in range(100)], 2: []}
    seen = fake_urlopen(monkeypatch, lambda request: pages[int(request.full_url.rsplit("page=", 1)[1])])
    assert len(prow.GitHub("projectbluefin/example", "tkn").labels("labels")) == 100
    assert len(seen) == 2


# --- emit_outputs -----------------------------------------------------------

def test_emit_outputs_appends_key_value_lines(tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.write_text("existing=1\n")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    prow.emit_outputs(execute="true", state=tmp_path / "s.json", command="")
    assert output.read_text() == f"existing=1\nexecute=true\nstate={tmp_path / 's.json'}\ncommand=\n"


@pytest.mark.parametrize("value", ["a\nb", "a\rb", "x\n"])
def test_emit_outputs_refuses_multiline_values(tmp_path, monkeypatch, value):
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    with pytest.raises(ValueError, match="single-line"):
        prow.emit_outputs(command=value)
    assert "command=" not in output.read_text()


# --- main() -----------------------------------------------------------------

@pytest.fixture
def actions_env(tmp_path, monkeypatch, catalog):  # noqa: F811
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(json.dumps(catalog))
    output = tmp_path / "github_output"
    output.write_text("")
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": catalog["repository"],
        "GITHUB_OUTPUT": str(output),
        "GITHUB_EVENT_NAME": "issue_comment",
        "RUNNER_TEMP": str(runner_temp),
        "GH_TOKEN": "tkn",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    return {"catalog": catalog_file, "output": output, "runner_temp": runner_temp, "tmp": tmp_path}


def outputs(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def install_client(monkeypatch, factory):
    built = []

    def _github(repository, token, api_url="https://api.github.com"):
        built.append((repository, token, api_url))
        return factory()

    monkeypatch.setattr(prow, "GitHub", _github)
    return built


class NoNetwork:
    def request(self, *args, **kwargs):
        raise AssertionError("main() must not call GitHub on this path")

    labels = file_json = request


def write_event(env, monkeypatch, payload):
    path = env["tmp"] / "event.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))


@pytest.mark.parametrize("unset", ["absent", "false", "1"])
def test_main_refuses_outside_github_actions(actions_env, monkeypatch, unset):
    if unset == "absent":
        monkeypatch.delenv("GITHUB_ACTIONS")
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", unset)
    built = install_client(monkeypatch, NoNetwork)
    with pytest.raises(ValueError, match="require GitHub Actions"):
        prow.main(["prepare", "--catalog", str(actions_env["catalog"])])
    assert built == []


def test_main_refuses_a_catalog_for_another_repository(actions_env, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "projectbluefin/other")
    built = install_client(monkeypatch, NoNetwork)
    with pytest.raises(ValueError, match="scoped to GITHUB_REPOSITORY"):
        prow.main(["prepare", "--catalog", str(actions_env["catalog"])])
    assert built == []


@pytest.mark.parametrize("repository", ["ublue-os/bluefin", "UBlue-OS/bluefin", "owner/repo/extra", "owner", "own er/repo", "owner/", "/repo"])
def test_main_refuses_unsupported_repository_scopes(actions_env, monkeypatch, catalog, repository):  # noqa: F811
    scoped = dict(catalog, repository=repository)
    actions_env["catalog"].write_text(json.dumps(scoped))
    monkeypatch.setenv("GITHUB_REPOSITORY", repository)
    built = install_client(monkeypatch, NoNetwork)
    with pytest.raises(ValueError, match="Unsupported repository scope"):
        prow.main(["prepare", "--catalog", str(actions_env["catalog"])])
    assert built == []


def test_main_builds_the_client_from_token_and_api_url(actions_env, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example/api/v3")
    built = install_client(monkeypatch, NoNetwork)
    prow.main(["prepare", "--catalog", str(actions_env["catalog"])])
    assert built == [("projectbluefin/example", "tkn", "https://ghe.example/api/v3")]


@pytest.mark.parametrize("event_name", ["issues", "pull_request_target", "workflow_dispatch"])
def test_prepare_on_other_events_emits_no_execution_and_reads_nothing(actions_env, monkeypatch, event_name):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    install_client(monkeypatch, NoNetwork)
    assert prow.main(["prepare", "--catalog", str(actions_env["catalog"])]) == 0
    assert outputs(actions_env["output"]) == {"execute": "false", "state": ""}


def test_prepare_refuses_an_event_from_another_repository(actions_env, monkeypatch, event):  # noqa: F811
    payload = deepcopy(event)
    payload["repository"]["full_name"] = "attacker/fork"
    write_event(actions_env, monkeypatch, payload)
    install_client(monkeypatch, NoNetwork)
    with pytest.raises(ValueError, match="Immutable event repository differs"):
        prow.main(["prepare", "--catalog", str(actions_env["catalog"])])
    assert actions_env["output"].read_text() == ""


def test_prepare_on_ordinary_discussion_emits_no_execution(actions_env, monkeypatch, event):  # noqa: F811
    payload = deepcopy(event)
    payload["comment"]["body"] = "Thanks, looks good."
    write_event(actions_env, monkeypatch, payload)
    install_client(monkeypatch, NoNetwork)
    assert prow.main(["prepare", "--catalog", str(actions_env["catalog"])]) == 0
    assert outputs(actions_env["output"]) == {"execute": "false", "state": ""}
    assert list(actions_env["runner_temp"].iterdir()) == []


def test_prepare_writes_state_to_runner_temp_and_emits_upstream_inputs(actions_env, monkeypatch, catalog, event):  # noqa: F811
    write_event(actions_env, monkeypatch, event)
    install_client(monkeypatch, lambda: FixtureGitHub(catalog, event))

    assert prow.main(["prepare", "--catalog", str(actions_env["catalog"])]) == 0

    out = outputs(actions_env["output"])
    assert out["execute"] == "true"
    assert out["config"] == f"projectbluefin/example:.github/prow.yaml@{'a' * 40}"
    assert out["command"]
    state_path = Path(out["state"])
    assert state_path.parent == actions_env["runner_temp"]
    assert state_path.name.startswith("prow-command-") and state_path.suffix == ".json"
    state = json.loads(state_path.read_text())
    assert state["execute"] is True
    assert state["number"] == 12
    assert out["command"] == state["upstream_command"]


def test_prepare_forwards_catalog_path_to_the_default_branch_read(actions_env, monkeypatch, catalog, event):  # noqa: F811
    write_event(actions_env, monkeypatch, event)
    reads = []

    class Recording(FixtureGitHub):
        def file_json(self, path, ref):
            reads.append(path)
            return self.catalog if path == "config/policy.json" else self.config

    install_client(monkeypatch, lambda: Recording(catalog, event))
    prow.main(["prepare", "--catalog", str(actions_env["catalog"]), "--catalog-path", "config/policy.json"])
    assert reads == ["config/policy.json", ".github/prow.yaml"]
    assert outputs(actions_env["output"])["execute"] == "true"


def test_prepare_denial_still_emits_state_so_report_can_explain(actions_env, monkeypatch, catalog, event):  # noqa: F811
    write_event(actions_env, monkeypatch, event)

    def reader():
        api = FixtureGitHub(catalog, event)
        api.permission = "read"
        return api

    install_client(monkeypatch, reader)
    assert prow.main(["prepare", "--catalog", str(actions_env["catalog"])]) == 0
    out = outputs(actions_env["output"])
    assert out["execute"] == "false"
    state = json.loads(Path(out["state"]).read_text())
    assert state["result"]["outcome"] == "denied"


def report_state(env, catalog, event, monkeypatch, *, execute, current=None):  # noqa: F811
    api = FixtureGitHub(catalog, event)
    state = prow.prepare(event, catalog, api)
    state["execute"] = execute
    path = env["tmp"] / "state.json"
    path.write_text(json.dumps(state))
    if current is not None:
        api.current = current
    install_client(monkeypatch, lambda: api)
    return path, api


def test_report_succeeds_when_observed_labels_match(actions_env, monkeypatch, catalog, event):  # noqa: F811
    api = FixtureGitHub(catalog, event)
    expected = set(prow.prepare(event, catalog, api)["expected"])
    path, api = report_state(actions_env, catalog, event, monkeypatch, execute=True, current=expected)

    code = prow.main(["report", "--catalog", str(actions_env["catalog"]), "--state", str(path), "--upstream-outcome", "success"])

    assert code == 0
    assert outputs(actions_env["output"]) == {"outcome": "applied"}
    assert [call[0] for call in api.calls if call[1] == "issues/12/comments"] == ["POST"]


@pytest.mark.parametrize("upstream", ["failure", "skipped", "cancelled"])
def test_report_fails_the_step_when_an_executed_command_did_not_apply(actions_env, monkeypatch, catalog, event, upstream):  # noqa: F811
    path, _ = report_state(actions_env, catalog, event, monkeypatch, execute=True)
    code = prow.main(["report", "--catalog", str(actions_env["catalog"]), "--state", str(path), "--upstream-outcome", upstream])
    assert code == 1
    assert outputs(actions_env["output"]) == {"outcome": "invalid"}


def test_report_defaults_upstream_outcome_to_skipped(actions_env, monkeypatch, catalog, event):  # noqa: F811
    api = FixtureGitHub(catalog, event)
    expected = set(prow.prepare(event, catalog, api)["expected"])
    path, _ = report_state(actions_env, catalog, event, monkeypatch, execute=True, current=expected)
    assert prow.main(["report", "--catalog", str(actions_env["catalog"]), "--state", str(path)]) == 1
    assert outputs(actions_env["output"]) == {"outcome": "invalid"}


def test_report_of_a_refused_command_publishes_but_does_not_fail(actions_env, monkeypatch, catalog, event):  # noqa: F811
    path, api = report_state(actions_env, catalog, event, monkeypatch, execute=False)
    state = json.loads(path.read_text())
    state["result"] = prow.result("/kind feature", "denied", "No.", catalog)
    path.write_text(json.dumps(state))

    assert prow.main(["report", "--catalog", str(actions_env["catalog"]), "--state", str(path)]) == 0
    assert outputs(actions_env["output"]) == {"outcome": "denied"}
    assert any(method == "POST" for method, _, _ in api.calls)


def test_report_propagates_an_unconfirmed_result_comment(actions_env, monkeypatch, catalog, event):  # noqa: F811
    path, api = report_state(actions_env, catalog, event, monkeypatch, execute=False)
    api.comment_response = False
    with pytest.raises(prow.ApiError, match="did not confirm"):
        prow.main(["report", "--catalog", str(actions_env["catalog"]), "--state", str(path)])
    assert actions_env["output"].read_text() == ""


# --- __main__ ---------------------------------------------------------------

def test_module_entrypoint_turns_refusals_into_exit_1_with_a_message(tmp_path, catalog):  # noqa: F811
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(json.dumps(catalog))
    env = {key: value for key, value in os.environ.items() if not key.startswith("GITHUB_")}
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.prow_commands", "prepare", "--catalog", str(catalog_file)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 1
    assert completed.stderr.startswith("Prow could not complete or publish its result: ")
    assert "require GitHub Actions" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_module_entrypoint_reports_a_missing_catalog_file(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.prow_commands", "prepare", "--catalog", str(tmp_path / "missing.json")],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 1
    assert "Prow could not complete or publish its result:" in completed.stderr
    assert "Traceback" not in completed.stderr
