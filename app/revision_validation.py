"""Validate a Ruff import fix from a pinned commit without modifying Git.

The Git worktree used by preview_committed_import_fix is a workspace, NOT an
OS security sandbox. Only Ruff (not source code) runs in a restricted Docker
container. The caller must supply a Jenkins-verified commit and file finding.
"""

import difflib
import os
import subprocess
import tempfile
from pathlib import Path

from app.docker_validator import validate_imports_in_docker
from app.revision_remediation import preview_committed_import_fix


def validate_pinned_import_fix(
    repo: Path,
    revision: str,
    category: str,
    candidate_files: list[str],
    path: str,
    ruff_binary: Path,
) -> dict:
    """Reconstruct a proposed import fix, then check it inside restricted Docker.

    Neither this function nor Ruff executes the checked-out Python source.
    This is *import-order validation only*, not an application test suite.
    """
    preview = preview_committed_import_fix(
        repo, revision, category, candidate_files, path
    )
    if "error" in preview:
        return {"status": "blocked", "error": "Pinned preview refused"}

    base = {
        "commit": preview["commit"],
        "path": preview["path"],
        "changed": preview["changed"],
        "applied_to_repository": False,
        "application_tests_executed": False,
        "review_required": True,
    }
    if not preview["changed"]:
        return {**base, "status": "no_change", "validation": "not_run"}

    try:
        if not Path(ruff_binary).is_file():
            return {**base, "status": "unavailable", "validation": "ruff_missing"}
        ruff = Path(ruff_binary).resolve(strict=True)
        if not os.access(ruff, os.X_OK):
            return {**base, "status": "unavailable", "validation": "ruff_missing"}

        # The SHA/path have already passed the strict pinned-preview checks.
        result = subprocess.run(
            ["git", "-C", str(Path(repo).resolve()), "show", f"{revision}:{path}"],
            capture_output=True,
            check=True,
            timeout=15,
        )
        original = result.stdout.decode("utf-8")
        if len(result.stdout) > 128_000 or b"\x00" in result.stdout:
            return {**base, "status": "unavailable", "validation": "invalid_source"}

        with tempfile.TemporaryDirectory(prefix="ci-pinned-ruff-") as directory:
            target = Path(directory) / "candidate.py"
            target.write_text(original, encoding="utf-8")
            fixed = subprocess.run(
                [str(ruff), "check", "--isolated", "--fix", "--select", "I",
                 "--no-cache", str(target)],
                cwd=directory,
                capture_output=True,
                timeout=20,
                check=False,
            )
            if fixed.returncode != 0:
                return {**base, "status": "unavailable", "validation": "ruff_fix_failed"}
            proposed = target.read_text(encoding="utf-8")

        # Ensure the exact proposed content matches the reviewed local preview.
        reproduced_diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        ))
        if reproduced_diff != preview["diff"]:
            return {**base, "status": "unavailable", "validation": "preview_mismatch"}

        validation = validate_imports_in_docker(proposed, ruff)
        status = (
            "validated" if validation.get("status") == "passed"
            else "failed" if validation.get("status") == "failed"
            else "unavailable"
        )
        # Keep the complete diff for LOCAL human review only. Hosted-model
        # adapters must explicitly remove it before making any Groq API call.
        return {
            **base,
            "status": status,
            "validation": "ruff_imports_only",
            "docker_result": validation.get("status", "unavailable"),
            "import_check_executed": validation.get("tests_executed", False),
            "diff": preview["diff"],
        }
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        return {**base, "status": "unavailable", "validation": "operation_failed"}


def main() -> None:
    """Demonstrate pinned fix validation using a disposable local Git repository."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate pinned Ruff fix")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if not args.demo:
        parser.error("Use --demo (live Jenkins integration is via Groq)")

    with tempfile.TemporaryDirectory(prefix="ci-revision-docker-demo-") as directory:
        repo = Path(directory)

        def git(*args: str) -> str:
            output = subprocess.run(
                ["git", "-C", str(repo), *args], capture_output=True,
                text=True, check=True, timeout=10,
            )
            return output.stdout.strip()

        git("init", "-q")
        git("config", "user.name", "DevSecOps Test")
        git("config", "user.email", "devsecops@example.invalid")
        (repo / "app").mkdir()
        file = repo / "app/example.py"
        file.write_text("import sys\nimport os\n\nprint(os.name, sys.version)\n")
        git("add", "app/example.py")
        git("commit", "-qm", "Create diagnostic fixture")
        sha = git("rev-parse", "HEAD")
        file.write_text("# Current working copy; must not be modified\n")

        result = validate_pinned_import_fix(
            repo, sha, "code_quality", ["app/example.py"],
            "app/example.py", Path.cwd() / ".venv/bin/ruff",
        )
        print("Validated commit:", sha[:12])
        print("Corrected candidate:", result["status"])
        print("Docker validation:", result.get("docker_result", "not_run"))
        print("Active working tree unchanged:", file.read_text().startswith("# Current"))
        print("Application tests executed:", result["application_tests_executed"])
        if result["status"] != "validated" or not file.read_text().startswith("# Current"):
            raise SystemExit("PINNED DOCKER VALIDATION DEMO FAILED")
        print("PINNED DOCKER VALIDATION DEMO PASSED")


if __name__ == "__main__":
    main()
