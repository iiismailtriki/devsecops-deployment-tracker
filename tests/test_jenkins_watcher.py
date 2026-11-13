"""Offline tests for stateful read-only Jenkins failure watching."""

import json
import stat

import pytest

from app.jenkins_watcher import SingleBuildClient, poll_once


class FakeJenkins:
    def __init__(self):
        self.current = [{
            "branch": "PR-3", "number": 1,
            "url": "http://127.0.0.1:8080/job/test/PR-3/1/",
        }]
        self.logs = []

    def failed_builds(self):
        return self.current

    def console_log(self, url):
        self.logs.append(url)
        return "Gitleaks issue\nFinished: FAILURE", False


def test_initial_poll_baselines_without_spending_model_calls(tmp_path):
    jenkins = FakeJenkins()
    calls = []
    state = tmp_path / "state/seen.json"

    result = poll_once(
        jenkins, lambda client: calls.append(client), state, tmp_path / "reports"
    )

    assert "baseline" in result
    assert json.loads(state.read_text()) == {"PR-3": 1}
    assert calls == []
    assert stat.S_IMODE(state.stat().st_mode) == 0o600


def test_new_failure_triggers_targeted_investigation_once(tmp_path):
    jenkins = FakeJenkins()
    state = tmp_path / "state/seen.json"
    reports = tmp_path / "reports"
    calls = []

    poll_once(jenkins, lambda client: "not called", state, reports)
    jenkins.current = [{
        "branch": "PR-3", "number": 2,
        "url": "http://127.0.0.1:8080/job/test/PR-3/2/",
    }]

    def investigate(client):
        calls.append(client.failed_builds()[0]["number"])
        return "AI report: suspected vulnerability; human review required."

    result = poll_once(jenkins, investigate, state, reports)
    assert "Investigation saved" in result
    assert calls == [2]
    report = next(reports.glob("*.md"))
    assert "AI report:" in report.read_text()
    assert stat.S_IMODE(report.stat().st_mode) == 0o600

    assert poll_once(jenkins, investigate, state, reports) == "No new failed builds."
    assert calls == [2]


def test_explicit_existing_failure_demo(tmp_path):
    jenkins = FakeJenkins()
    called = []
    result = poll_once(
        jenkins,
        lambda client: called.append(client.failed_builds()[0]["number"]) or "OK",
        tmp_path / "seen.json", tmp_path / "reports", process_existing=True,
    )
    assert "saved" in result
    assert called == [1]


def test_tool_scope_rejects_unlisted_build():
    jenkins = FakeJenkins()
    scoped = SingleBuildClient(jenkins, jenkins.current[0])
    with pytest.raises(ValueError):
        scoped.console_log("http://other-server/secret")
    assert not jenkins.logs


def test_failed_api_call_does_not_repeat_every_poll(tmp_path):
    jenkins = FakeJenkins()
    state = tmp_path / "seen.json"
    reports = tmp_path / "reports"

    def unavailable(_client):
        raise RuntimeError("private diagnostic must not print")

    result = poll_once(
        jenkins, unavailable, state, reports, process_existing=True,
    )
    assert "saved" in result
    assert "private diagnostic" not in next(reports.glob("*.md")).read_text()
    assert poll_once(jenkins, unavailable, state, reports) == "No new failed builds."
