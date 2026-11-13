from app.agent import run_agent, run_tool


class FakeJenkins:
    def failed_builds(self):
        return [{"branch": "PR-3", "number": 1,
                 "url": "http://127.0.0.1:8080/job/allowed"}]

    def console_log(self, url):
        return "Gitleaks: secret PAT:TOPSECRET", False


def test_agent_selects_tools_without_exposing_raw_log():
    client = FakeJenkins()
    transcripts = []

    def fake_llm(messages):
        transcripts.append(repr(messages))
        if len(transcripts) == 1:
            return {"output": [{"type": "function_call", "name": "list_failed_builds",
                                "arguments": "{}", "call_id": "call_1"}]}
        if len(transcripts) == 2:
            return {"output": [{"type": "function_call", "name": "inspect_failed_build",
                                "arguments": '{"branch": "PR-3", "number": 1}',
                                "call_id": "call_2"}]}
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "Gitleaks warning. Review manually."}]}]}

    result = run_agent(client, fake_llm)
    assert "Gitleaks warning" in result
    assert "TOPSECRET" not in repr(transcripts)


def test_agent_rejects_unlisted_build():
    result = run_tool(FakeJenkins(), "inspect_failed_build",
                      {"branch": "main", "number": 99})
    assert result == {"error": "Build not in allowed failed-build list"}


def test_agent_blocks_unapproved_actions():
    result = run_tool(FakeJenkins(), "run_shell", {"command": "rm -rf /"})
    assert result == {"error": "Tool not allowed"}


def test_agent_stops_when_model_repeats_calls():
    def repeat(messages):
        return {"output": [{"type": "function_call", "name": "list_failed_builds",
                            "arguments": "{}", "call_id": "repeat"}]}
    assert "safety limit" in run_agent(FakeJenkins(), repeat, max_steps=2)
