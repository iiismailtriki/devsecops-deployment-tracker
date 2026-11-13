"""Step 112: never permit the LLM to preview an unobserved source file."""
from app.ci_investigator import analyze_log
from app.remediation_bridge import safe_import_preview


def test_rejects_non_code_quality(tmp_path):
    result = safe_import_preview("secret_detection", ["app/demo.py"], {"path": "app/demo.py"}, tmp_path)
    assert "error" in result


def test_rejects_unobserved_paths(tmp_path):
    result = safe_import_preview("code_quality", ["app/safe.py"], {"path": "app/other.py"}, tmp_path)
    assert "error" in result


def test_rejects_unverified_candidate_list(tmp_path):
    result = safe_import_preview("code_quality", [], {"path": "app/a.py"}, tmp_path)
    assert "error" in result


def test_accepts_import_preview_without_source_leak(tmp_path):
    (tmp_path / "app").mkdir()
    source = tmp_path / "app" / "sample.py"
    original = "import sys\nimport os\n\nprint(os.name, sys.version)\n"
    source.write_text(original)
    result = safe_import_preview("code_quality", ["app/sample.py"], {"path": "app/sample.py"}, tmp_path)
    assert result["changed"] is True
    assert result["applied_to_repository"] is False
    assert result["tests_executed"] is False
    assert "diff" not in result
    assert source.read_text() == original


def test_ruff_I001_classifier_requires_failure_and_extracts_path():
    log = "I001 [*] Import block is un-sorted\n --> app/sample.py:1:1\nFinished: FAILURE\n"
    result = analyze_log(log)
    assert result["category"] == "code_quality"
    assert result["candidate_files"] == ["app/sample.py"]
    assert analyze_log(log.replace("FAILURE", "SUCCESS"))["status"] == "success"


def test_groq_agent_selects_preview_after_confirmed_ruff_failure(monkeypatch):
    import json

    from app import groq_agent

    calls = []

    def fake_run_tool(_jenkins, name, _args):
        if name == "list_failed_builds":
            return [{"branch": "main", "number": 9}]
        if name == "inspect_failed_build":
            return {"analysis": {
                "status": "failure_detected",
                "category": "code_quality",
                "candidate_files": ["app/main.py"],
            }}
        raise AssertionError("Unexpected Jenkins tool")

    def fake_preview(category, paths, args, _root):
        assert category == "code_quality"
        assert paths == ["app/main.py"]
        assert args == {"path": "app/main.py"}
        return {"changed": True, "applied_to_repository": False}

    monkeypatch.setattr(groq_agent, "run_tool", fake_run_tool)
    monkeypatch.setattr(groq_agent, "safe_import_preview", fake_preview)

    def response(_messages, choice):
        calls.append(choice)
        index = len(calls)
        if index == 1:
            name, arguments = "list_failed_builds", {}
        elif index == 2:
            name, arguments = "inspect_failed_build", {"branch": "main", "number": 9}
        elif index == 3:
            assert choice == "auto"
            name, arguments = "preview_import_sort", {"path": "app/main.py"}
        else:
            assert choice == "none"
            return {"choices": [{"message": {"content": "Preview available; no files changed."}}]}
        return {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": f"call{index}", "type": "function", "function": {
                "name": name, "arguments": json.dumps(arguments)
            },
        }]}}]}

    report = groq_agent.run_groq_agent(object(), response)
    assert "no files changed" in report
    assert len(calls) == 4


def test_groq_agent_prohibits_preview_for_gitleaks(monkeypatch):
    import json

    from app import groq_agent

    def fake_run_tool(_jenkins, name, _args):
        if name == "list_failed_builds":
            return [{"branch": "PR-3", "number": 1}]
        return {"analysis": {
            "status": "failure_detected",
            "category": "secret_detection",
            "candidate_files": ["app/main.py"],
        }}

    monkeypatch.setattr(groq_agent, "run_tool", fake_run_tool)

    counter = [0]

    def response(_messages, choice):
        counter[0] += 1
        if counter[0] == 3:
            assert choice == "none"
            return {"choices": [{"message": {"content": "Human review required."}}]}
        name = "list_failed_builds" if counter[0] == 1 else "inspect_failed_build"
        args = {} if counter[0] == 1 else {"branch": "PR-3", "number": 1}
        return {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": f"call{counter[0]}", "type": "function", "function": {
                "name": name, "arguments": json.dumps(args)
            },
        }]}}]}

    assert groq_agent.run_groq_agent(object(), response) == "Human review required."
