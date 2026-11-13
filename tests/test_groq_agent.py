"""No-live-API tests for the Groq Jenkins investigator."""

import pytest

from app.groq_agent import API_URL, call_groq, run_groq_agent


class FakeJenkins:
    def failed_builds(self):
        return [{
            "branch": "PR-3", "number": 1,
            "url": "http://127.0.0.1:8080/job/allowed",
        }]

    def console_log(self, url):
        return "Gitleaks: secret PAT:TOPSECRET\nFinished: FAILURE", False


def tool_message(name, args, call_id):
    return {"choices": [{"message": {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": args},
        }],
    }}]}


def test_agent_inspects_real_build_without_sending_raw_secrets():
    seen = []
    replies = [
        tool_message("list_failed_builds", "{}", "call_1"),
        tool_message("inspect_failed_build", '{"branch":"PR-3","number":1}', "call_2"),
        {"choices": [{"message": {
            "role": "assistant", "content": "Gitleaks detected a finding; review it."
        }}]},
    ]

    def fake_completion(messages, choice):
        seen.append((repr(messages), choice))
        return replies[len(seen) - 1]

    report = run_groq_agent(FakeJenkins(), fake_completion)
    assert "Gitleaks" in report
    assert all("TOPSECRET" not in text for text, _ in seen)
    assert seen[0][1]["function"]["name"] == "list_failed_builds"
    assert seen[1][1]["function"]["name"] == "inspect_failed_build"
    assert seen[2][1] == "none"


def test_no_made_up_report_without_inspection():
    def fake_completion(messages, choice):
        return {"choices": [{"message": {"role": "assistant", "content": "I fixed it"}}]}

    assert "No failed build" in run_groq_agent(FakeJenkins(), fake_completion)


def test_unknown_tool_is_blocked():
    responses = [tool_message("run_shell", '{"cmd":"rm -rf /"}', "call_x")]

    def fake_completion(messages, choice):
        if responses:
            return responses.pop(0)
        return {"choices": [{"message": {"content": "All done"}}]}

    result = run_groq_agent(FakeJenkins(), fake_completion, max_turns=2)
    assert "No failed build" in result


def test_groq_request_uses_correct_chat_api(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "hello"}}]}

    def fake_post(url, *, headers, json, timeout):
        assert url == API_URL
        assert headers["Authorization"] == "Bearer fake-key"
        assert json["model"] == "openai/gpt-oss-20b"
        assert json["parallel_tool_calls"] is False
        assert timeout == 45
        return FakeResponse()

    monkeypatch.setattr("app.groq_agent.requests.post", fake_post)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    assert call_groq([{"role": "user", "content": "hi"}], "fake-key")


def test_groq_rate_limit_has_safe_error(monkeypatch):
    class FakeResponse:
        status_code = 429

        def json(self):
            return {"error": {"code": "rate_limit_exceeded", "message": "secret value"}}

    monkeypatch.setattr(
        "app.groq_agent.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )
    with pytest.raises(RuntimeError, match="rate_limit_exceeded") as err:
        call_groq([], "fake-key")
    assert "secret value" not in str(err.value)
