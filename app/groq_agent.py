"""Bounded Jenkins investigation agent with an import-only preview tool."""

import getpass
import json
import os
from pathlib import Path

import requests

from app.agent import INSTRUCTIONS, run_tool
from app.jenkins_client import JenkinsClient
from app.pinned_remediation_bridge import (
    safe_pinned_import_preview,
    safe_pinned_import_validation,
)

API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_failed_builds",
            "description": "List previous failed Jenkins builds, one per branch. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_failed_build",
            "description": (
                "Inspect a build from list_failed_builds. Return classified, "
                "non-raw diagnostic evidence; never send console logs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {"type": "string"},
                    "number": {"type": "integer"},
                },
                "required": ["branch", "number"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_import_sort",
            "description": (
                "Preview Ruff import-order corrections ONLY for a diagnosed Ruff "
                "code-quality failure. The source file must appear in the Jenkins "
                "finding, and a Jenkins-verified commit is required. "
                "No repository edits, tests, or PRs are performed."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_import_fix",
            "description": (
                "After a successful preview_import_sort, validate the SAME authorized "
                "Ruff import-order correction in restricted Docker using the "
                "Jenkins-verified commit. Returns metadata only. Does not run "
                "application tests, change Git, or create a PR."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]


def call_groq(messages, api_key, tool_choice="auto"):
    """Call Groq without printing or storing the API key or raw HTTP body."""
    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": os.environ.get("GROQ_MODEL", DEFAULT_MODEL),
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": tool_choice,
            "parallel_tool_calls": False,
            "max_completion_tokens": 1800,
        },
        timeout=45,
    )
    if response.status_code != 200:
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        if not isinstance(error, dict):
            error = {}
        code = error.get("code")
        safe_code = code if isinstance(code, str) and code.isidentifier() else "unknown"
        raise RuntimeError(f"Groq API HTTP {response.status_code}; code={safe_code}")
    return response.json()


def run_groq_agent(jenkins, completion, max_turns=5):
    """Select a failed build with the model, inspect safely, then report."""
    messages = [
        {"role": "system", "content": INSTRUCTIONS + (
            " You can use only the tools provided. Never invent tool results. "
            "Never claim a patch was applied or tests were run. "
             "Only suggest preview_import_sort for code-quality failures with a "
             "candidate file found in the Jenkins evidence. "
             "After a successful preview, validate the same proposed import "
             "fix in Docker when appropriate; validation runs only Ruff. "
             "A verified Jenkins commit is mandatory; no fallback to the "
             "current working tree. The tool returns metadata, no diffs."
        )},
        {"role": "user", "content": (
            "Find and inspect a previous failed Jenkins build using tools. "
            "Report the observed evidence, probable cause, and review steps."
        )},
    ]
    inspected = False
    have_list = False
    inspected_category = None
    allowed_paths = []
    preview_attempted = False
    preview_path = None
    validation_attempted = False
    inspected_revision = None
    for _ in range(max_turns):
        if inspected:
            eligible = (
                inspected_category == "code_quality"
                and allowed_paths and inspected_revision is not None
            )
            choice = (
                "auto" if eligible and (
                    not preview_attempted or (
                        preview_path is not None and not validation_attempted
                    )
                ) else "none"
            )
        elif not have_list:
            choice = {"type": "function", "function": {"name": "list_failed_builds"}}
        else:
            choice = {"type": "function", "function": {"name": "inspect_failed_build"}}

        response = completion(messages, choice)
        choices = response.get("choices", [])
        if not choices or not isinstance(choices[0].get("message"), dict):
            raise RuntimeError("Groq returned no usable message")
        message = choices[0]["message"]
        calls = message.get("tool_calls") or []

        if not calls:
            if not inspected:
                return "No failed build was inspected; no diagnosis generated."
            content = message.get("content")
            return content.strip() if isinstance(content, str) and content.strip() else (
                "Build inspected, but the model produced no report."
            )

        if not isinstance(calls, list) or len(calls) > 3:
            raise RuntimeError("Invalid or excessive tool calls")
        messages.append({
            "role": "assistant",
            "content": message.get("content"),
            "tool_calls": calls,
        })

        for call in calls:
            function = call.get("function", {})
            name = function.get("name")
            if name == "preview_import_sort":
                preview_attempted = True
                try:
                    args = json.loads(function.get("arguments", "{}"))
                    result = safe_pinned_import_preview(
                        inspected_category if inspected else None,
                        allowed_paths,
                        inspected_revision,
                        args,
                        Path(__file__).resolve().parents[1],
                    )
                    if result.get("changed") is True and "error" not in result:
                        preview_path = result.get("path")
                except (ValueError, TypeError, RuntimeError, OSError):
                    result = {"error": "Import preview rejected or failed"}
            elif name == "validate_import_fix":
                validation_attempted = True
                try:
                    args = json.loads(function.get("arguments", "{}"))
                    if (
                        preview_path is None or not isinstance(args, dict)
                        or set(args) != {"path"}
                        or args["path"] != preview_path
                    ):
                        result = {"error": "Validation requires successful preview of same file"}
                    else:
                        result = safe_pinned_import_validation(
                            inspected_category if inspected else None,
                            allowed_paths,
                            inspected_revision,
                            args,
                            Path(__file__).resolve().parents[1],
                        )
                except (ValueError, TypeError, RuntimeError, OSError):
                    result = {"error": "Import validation rejected or failed"}
            elif name not in {"list_failed_builds", "inspect_failed_build"}:
                result = {"error": "Tool not allowed"}
            else:
                try:
                    args = json.loads(function.get("arguments", "{}"))
                    if not isinstance(args, dict):
                        raise TypeError("Tool arguments must be an object")
                    result = run_tool(jenkins, name, args)
                    if name == "list_failed_builds" and isinstance(result, list):
                        have_list = True
                    if name == "inspect_failed_build" and isinstance(result, dict):
                        analysis = result.get("analysis")
                        if isinstance(analysis, dict):
                            inspected = True
                            if analysis.get("status") == "failure_detected":
                                inspected_category = analysis.get("category")
                                paths = analysis.get("candidate_files", [])
                                allowed_paths = paths if isinstance(paths, list) else []
                                revision = result.get("revision")
                                inspected_revision = (
                                    revision if isinstance(revision, dict)
                                    and revision.get("status") == "verified"
                                    and revision.get("source") == "jenkins_lastBuiltRevision"
                                    else None
                                )
                except (ValueError, TypeError, KeyError, requests.RequestException, RuntimeError):
                    result = {"error": "Tool failed or arguments invalid"}

            tool_label = (
                name if name in {
                    "list_failed_builds", "inspect_failed_build",
                    "preview_import_sort", "validate_import_fix",
                }
                else "blocked"
            )
            print(f"  Tool used: {tool_label}")
            if name == "list_failed_builds" and result == []:
                return "Jenkins reported no previous failed builds in the allowed list."
            messages.append({
                "role": "tool",
                "tool_call_id": str(call.get("id", "missing")),
                "content": json.dumps(result),
            })

    return "Agent stopped at its safety limit without a final diagnosis."


def main():
    print("Groq-powered Jenkins investigator (read-only)")
    username = input("Jenkins username [ismail]: ").strip() or "ismail"
    jenkins_token = getpass.getpass("Jenkins API token: ")
    groq_key = os.getenv("GROQ_API_KEY") or getpass.getpass("Groq API key: ")
    if not groq_key:
        print("No Groq API key provided; no AI request made.")
        return
    client = JenkinsClient(username, jenkins_token)
    try:
        report = run_groq_agent(
            client,
            lambda messages, choice: call_groq(messages, groq_key, choice),
        )
        print("\n=== AI Investigation ===")
        print(report)
    except (requests.RequestException, RuntimeError) as error:
        # Avoid printing request objects, response bodies, or credentials.
        if isinstance(error, RuntimeError):
            print(f"Agent unavailable: {error}")
        else:
            print(f"Agent unavailable: {type(error).__name__}")


if __name__ == "__main__":
    main()
