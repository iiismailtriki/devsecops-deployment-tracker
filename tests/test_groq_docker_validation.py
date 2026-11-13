"""Groq validation tool is gated on a successful same-file preview."""

import json

from app import groq_agent
from app import pinned_remediation_bridge as bridge

SHA = "a" * 40
VERIFIED = {"status": "verified", "commit": SHA, "source": "jenkins_lastBuiltRevision"}


def tool(name, args, number):
    return {"choices": [{"message": {"content": None, "tool_calls": [{
        "id": f"call{number}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }]}}]}


def fake_build_tool(_client, name, _args):
    if name == "list_failed_builds":
        return [{"branch": "main", "number": 3}]
    return {"analysis": {
        "status": "failure_detected", "category": "code_quality",
        "candidate_files": ["app/example.py"],
    }, "revision": VERIFIED}


def test_validated_preview_lets_groq_call_docker_once(monkeypatch):
    monkeypatch.setattr(groq_agent, "run_tool", fake_build_tool)
    monkeypatch.setattr(groq_agent, "safe_pinned_import_preview", lambda *_: {
        "path": "app/example.py", "changed": True, "mode": "preview_only",
    })
    calls = []

    def fake_validate(_category, _paths, _revision, args, _repo):
        calls.append(args)
        return {"status": "validated", "docker_result": "passed"}

    monkeypatch.setattr(groq_agent, "safe_pinned_import_validation", fake_validate)
    turns = [0]

    def completion(_messages, choice):
        turns[0] += 1
        if turns[0] == 1:
            return tool("list_failed_builds", {}, 1)
        if turns[0] == 2:
            return tool("inspect_failed_build", {"branch": "main", "number": 3}, 2)
        if turns[0] == 3:
            assert choice == "auto"
            return tool("preview_import_sort", {"path": "app/example.py"}, 3)
        if turns[0] == 4:
            assert choice == "auto"
            return tool("validate_import_fix", {"path": "app/example.py"}, 4)
        assert choice == "none"
        return {"choices": [{"message": {"content": "Ruff import check passed; PR pending review."}}]}

    report = groq_agent.run_groq_agent(object(), completion)
    assert "Ruff import check passed" in report
    assert calls == [{"path": "app/example.py"}]


def test_validation_before_preview_refused(monkeypatch):
    monkeypatch.setattr(groq_agent, "run_tool", fake_build_tool)
    monkeypatch.setattr(groq_agent, "safe_pinned_import_validation", lambda *_: (
        (_ for _ in ()).throw(AssertionError("must not validate"))
    ))
    turn = [0]

    def completion(messages, _choice):
        turn[0] += 1
        if turn[0] == 1:
            return tool("list_failed_builds", {}, 1)
        if turn[0] == 2:
            return tool("inspect_failed_build", {"branch": "main", "number": 3}, 2)
        if turn[0] == 3:
            return tool("validate_import_fix", {"path": "app/example.py"}, 3)
        assert "successful preview" in messages[-1]["content"]
        return {"choices": [{"message": {"content": "Validation rejected."}}]}

    assert "rejected" in groq_agent.run_groq_agent(object(), completion)


def test_wrong_path_after_preview_refused(monkeypatch):
    monkeypatch.setattr(groq_agent, "run_tool", fake_build_tool)
    monkeypatch.setattr(groq_agent, "safe_pinned_import_preview", lambda *_: {
        "path": "app/example.py", "changed": True,
    })
    monkeypatch.setattr(groq_agent, "safe_pinned_import_validation", lambda *_: (
        (_ for _ in ()).throw(AssertionError("must not validate wrong file"))
    ))
    turns = [0]

    def completion(messages, _choice):
        turns[0] += 1
        if turns[0] == 1:
            return tool("list_failed_builds", {}, 1)
        if turns[0] == 2:
            return tool("inspect_failed_build", {"branch": "main", "number": 3}, 2)
        if turns[0] == 3:
            return tool("preview_import_sort", {"path": "app/example.py"}, 3)
        if turns[0] == 4:
            return tool("validate_import_fix", {"path": "tests/other.py"}, 4)
        assert "successful preview" in messages[-1]["content"]
        return {"choices": [{"message": {"content": "Unsafe request blocked."}}]}

    assert "blocked" in groq_agent.run_groq_agent(object(), completion)


def test_model_ignores_validation_when_gitleaks(monkeypatch):
    def fake_tool(_client, name, _args):
        if name == "list_failed_builds":
            return [{"branch": "PR-3", "number": 1}]
        return {"analysis": {
            "status": "failure_detected", "category": "secret_detection",
            "candidate_files": ["app/example.py"],
        }, "revision": VERIFIED}

    monkeypatch.setattr(groq_agent, "run_tool", fake_tool)
    monkeypatch.setattr(groq_agent, "safe_pinned_import_validation", lambda *_: (
        (_ for _ in ()).throw(AssertionError("must not validate secret detection"))
    ))
    count = [0]

    def completion(messages, choice):
        count[0] += 1
        if count[0] == 1:
            return tool("list_failed_builds", {}, 1)
        if count[0] == 2:
            return tool("inspect_failed_build", {"branch": "PR-3", "number": 1}, 2)
        assert choice == "none"
        return {"choices": [{"message": {"content": "Human review required."}}]}

    assert groq_agent.run_groq_agent(object(), completion) == "Human review required."


def test_bridge_hides_patch_content(monkeypatch, tmp_path):
    def fake_validate(*_args):
        return {
            "commit": SHA,
            "path": "app/example.py",
            "changed": True,
            "status": "validated",
            "validation": "ruff_imports_only",
            "docker_result": "passed",
            "import_check_executed": True,
            "diff": "CONFIDENTIAL_LOCAL_SOURCE_PATCH",
        }

    monkeypatch.setattr(bridge, "validate_pinned_import_fix", fake_validate)
    result = bridge.safe_pinned_import_validation(
        "code_quality", ["app/example.py"], VERIFIED,
        {"path": "app/example.py"}, tmp_path,
    )
    assert result["status"] == "validated"
    assert result["application_tests_executed"] is False
    assert "CONFIDENTIAL_LOCAL_SOURCE_PATCH" not in str(result)
    assert "diff" not in result


def test_bridge_denies_unverified_commit(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "validate_pinned_import_fix", lambda *_: (
        (_ for _ in ()).throw(AssertionError("must not execute"))
    ))
    result = bridge.safe_pinned_import_validation(
        "code_quality", ["app/example.py"], {"status": "unavailable"},
        {"path": "app/example.py"}, tmp_path,
    )
    assert "error" in result


def test_bridge_denies_secret_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "validate_pinned_import_fix", lambda *_: (
        (_ for _ in ()).throw(AssertionError("must not execute"))
    ))
    result = bridge.safe_pinned_import_validation(
        "secret_detection", ["app/example.py"], VERIFIED,
        {"path": "app/example.py"}, tmp_path,
    )
    assert "error" in result
