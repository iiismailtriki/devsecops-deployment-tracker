"""Revision-pinned, review-only Ruff remediation tool for hosted LLMs.

Never sends patches/source to the model; never falls back to a live checkout.
"""

import re
from pathlib import Path

from app.revision_remediation import preview_committed_import_fix
from app.revision_validation import validate_pinned_import_fix

SHA = re.compile(r"[0-9a-fA-F]{40}\Z")


def safe_pinned_import_preview(category, candidate_files, revision, arguments, repo: Path) -> dict:
    """Require Jenkins-verified SHA + observed Ruff path before any preview.

    revision is read from the Jenkins collector, NOT from an LLM argument.
    """
    if category != "code_quality":
        return {"error": "Remediation prohibited for this failure category"}
    if not isinstance(candidate_files, list) or not candidate_files:
        return {"error": "No file authorized by the Jenkins failure evidence"}
    if not isinstance(arguments, dict) or set(arguments) != {"path"}:
        return {"error": "Expected only a path argument"}
    path = arguments["path"]
    if not isinstance(path, str) or path not in candidate_files:
        return {"error": "Path not authorized by the Jenkins failure evidence"}
    if not isinstance(revision, dict) or revision.get("status") != "verified":
        return {"error": "Jenkins failed-build revision is not verified"}
    commit = revision.get("commit")
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        return {"error": "Jenkins commit SHA is invalid"}
    if revision.get("source") != "jenkins_lastBuiltRevision":
        return {"error": "Untrusted Git revision source"}

    result = preview_committed_import_fix(
        Path(repo), commit, category, candidate_files, path
    )
    if "error" in result:
        return {"error": "Pinned revision preview refused"}
    # Never return result['diff'] or any raw source to a hosted model.
    return {
        "mode": "preview_only",
        "commit": result["commit"],
        "path": result["path"],
        "changed": result["changed"],
        "applied_to_repository": False,
        "tests_executed": False,
        "review_required": True,
    }


def safe_pinned_import_validation(
    category, candidate_files, revision, arguments, repo: Path
) -> dict:
    """Safely validate an approved, commit-pinned import preview in Docker.

    The hosted model receives metadata only, never source code or local diffs.
    """
    if category != "code_quality":
        return {"error": "Validation prohibited for this failure category"}
    if not isinstance(candidate_files, list) or not candidate_files:
        return {"error": "No Jenkins-authorized Python file"}
    if not isinstance(arguments, dict) or set(arguments) != {"path"}:
        return {"error": "Expected only a path argument"}
    path = arguments["path"]
    if not isinstance(path, str) or path not in candidate_files:
        return {"error": "Path not authorized by Jenkins evidence"}
    if not isinstance(revision, dict) or revision.get("status") != "verified":
        return {"error": "Jenkins commit is not verified"}
    sha = revision.get("commit")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        return {"error": "Invalid commit SHA"}
    if revision.get("source") != "jenkins_lastBuiltRevision":
        return {"error": "Untrusted commit source"}

    result = validate_pinned_import_fix(
        Path(repo), sha, category, candidate_files, path,
        Path(repo) / ".venv/bin/ruff",
    )
    if "error" in result:
        return {"error": "Pinned Docker validation refused"}
    return {
        "mode": "validation_only",
        "commit": result["commit"],
        "path": result["path"],
        "changed": result["changed"],
        "status": result["status"],
        "validation": result["validation"],
        "docker_result": result.get("docker_result", "not_run"),
        "import_check_executed": result.get("import_check_executed", False),
        "application_tests_executed": False,
        "applied_to_repository": False,
        "review_required": True,
    }
