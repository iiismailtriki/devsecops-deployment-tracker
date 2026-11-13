"""Evidence-gated, metadata-only tool adapter for safe Ruff import previews."""
from pathlib import Path

from app.remediation import preview_import_sort


def safe_import_preview(category, candidate_files, arguments, repo: Path) -> dict:
    """Return only preview metadata to an LLM, never raw source or patch content.

    A real Jenkins Ruff finding must authorize the exact file path.
    """
    if category != "code_quality":
        return {"error": "Remediation is not permitted for this failure type"}
    if not isinstance(candidate_files, list) or not candidate_files:
        return {"error": "No file confirmed by Jenkins diagnostics"}
    if not isinstance(arguments, dict) or set(arguments) != {"path"}:
        return {"error": "Expected only a path argument"}
    path = arguments["path"]
    if not isinstance(path, str) or path not in candidate_files:
        return {"error": "File not present in observed Jenkins findings"}
    preview = preview_import_sort(repo, path)
    # Do not transmit the source-code diff to the hosted LLM.
    return {
        "mode": "preview_only",
        "path": preview["path"],
        "changed": preview["changed"],
        "applied_to_repository": False,
        "tests_executed": False,
        "review_command": f".venv/bin/python -m app.remediation --file {preview['path']}",
    }
