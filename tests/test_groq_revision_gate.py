"""The LLM is not allowed to remediate an unverified commit."""

import json

from app import groq_agent


def _tool(name, args, index):
    return {"choices": [{"message": {"content": None, "tool_calls": [{
        "id": f"call{index}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }]}}]}


def test_no_automatic_preview_without_verified_revision(monkeypatch):
    def fake_run_tool(_jenkins, name, _args):
        if name == "list_failed_builds":
            return [{"branch": "main", "number": 2}]
        return {"analysis": {
            "status": "failure_detected", "category": "code_quality",
            "candidate_files": ["app/main.py"],
        }, "revision": {"status": "unavailable"}}

    def forbidden(*_args):
        raise AssertionError("Unverified revision must never reach preview")

    monkeypatch.setattr(groq_agent, "run_tool", fake_run_tool)
    monkeypatch.setattr(groq_agent, "safe_pinned_import_preview", forbidden)
    seen = []

    def completion(_messages, choice):
        seen.append(choice)
        if len(seen) == 1:
            return _tool("list_failed_builds", {}, 1)
        if len(seen) == 2:
            return _tool("inspect_failed_build", {"branch": "main", "number": 2}, 2)
        assert choice == "none"
        return {"choices": [{"message": {"content": "Needs human review; revision unavailable."}}]}

    report = groq_agent.run_groq_agent(object(), completion)
    assert "revision unavailable" in report
    assert len(seen) == 3


def test_model_forced_preview_still_denied_without_revision(monkeypatch):
    def fake_run_tool(_jenkins, name, _args):
        if name == "list_failed_builds":
            return [{"branch": "main", "number": 2}]
        return {"analysis": {
            "status": "failure_detected", "category": "code_quality",
            "candidate_files": ["app/main.py"],
        }, "revision": {"status": "unavailable"}}

    monkeypatch.setattr(groq_agent, "run_tool", fake_run_tool)
    counts = []

    def fake_preview(category, paths, revision, args, _repo):
        counts.append((category, paths, revision, args))
        assert revision is None
        return {"error": "Jenkins failed-build revision is not verified"}

    monkeypatch.setattr(groq_agent, "safe_pinned_import_preview", fake_preview)

    turn = [0]

    def completion(messages, choice):
        turn[0] += 1
        if turn[0] == 1:
            return _tool("list_failed_builds", {}, 1)
        if turn[0] == 2:
            return _tool("inspect_failed_build", {"branch": "main", "number": 2}, 2)
        if turn[0] == 3:
            # Deliberately simulate a model violating 'tool_choice=none'.
            assert choice == "none"
            return _tool("preview_import_sort", {"path": "app/main.py"}, 3)
        assert choice == "none"
        tool_results = [m for m in messages if m.get("role") == "tool"]
        assert "not verified" in tool_results[-1]["content"]
        return {"choices": [{"message": {"content": "Preview refused."}}]}

    assert groq_agent.run_groq_agent(object(), completion) == "Preview refused."
    assert len(counts) == 1
