"""Review-only Ruff fix previews for the exact Git commit under investigation.

Temporary Git worktrees prevent edits to the active checkout; they are NOT
an OS security sandbox. This module never executes checked-out application code.
"""

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

from app.remediation import preview_import_sort

FULL_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
ALLOWED_PATH = re.compile(r"(?:app|tests)/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.py\Z")


def _git(repo: Path, *args: str) -> str:
    """Run a fixed, non-shell Git operation with a short time limit."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise RuntimeError("A local Git operation failed or timed out") from exc
    return result.stdout.strip()


def preview_committed_import_fix(
    repo: Path,
    revision: str,
    category: str,
    candidate_files: list[str],
    path: str,
) -> dict:
    """Preview a Ruff import fix from an explicitly pinned local Git commit.

    Requires a trusted, already-verified Jenkins category and candidate path.
    Does not fetch remote refs, run target code, apply a patch or create a PR.
    """
    if category != "code_quality":
        return {"error": "Remediation prohibited for this failure category"}
    if not isinstance(candidate_files, list) or not candidate_files:
        return {"error": "No file authorized by the CI failure evidence"}
    if not isinstance(path, str) or not ALLOWED_PATH.fullmatch(path):
        return {"error": "Only simple Python paths under app/ or tests/ are allowed"}
    if path not in candidate_files:
        return {"error": "Requested file not authorized by CI failure evidence"}
    if not isinstance(revision, str) or not FULL_SHA.fullmatch(revision):
        return {"error": "Expected a full 40-character commit SHA"}

    repo = Path(repo).resolve(strict=True)
    # Refuse untrusted ref names, tags and branch names; require a full commit.
    resolved = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if resolved.lower() != revision.lower():
        return {"error": "Git revision does not resolve to the requested commit"}

    with tempfile.TemporaryDirectory(prefix="ci-revision-review-") as temporary:
        checkout = Path(temporary) / "checkout"
        registered = False
        try:
            _git(repo, "worktree", "add", "--detach", str(checkout), revision)
            registered = True
            # Validated path is examined again by preview_import_sort, which
            # rejects symlinks and never runs or imports checked-out code.
            preview = preview_import_sort(checkout, path)
        finally:
            if registered:
                _git(repo, "worktree", "remove", "--force", str(checkout))

    return {
        "mode": "preview_only",
        "commit": resolved,
        "path": preview["path"],
        "changed": preview["changed"],
        "diff": preview["diff"],  # Local human review only: never send to a hosted LLM.
        "applied_to_repository": False,
        "tests_executed": False,
        "execution_isolation": "temporary_git_worktree_not_security_sandbox",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review Ruff import fix at a pinned Git revision"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Demonstrate a pinned revision without altering your repo",
    )
    args = parser.parse_args()
    if not args.demo:
        parser.error(
            "Use --demo; live Jenkins revision selection is not implemented yet"
        )

    with tempfile.TemporaryDirectory(prefix="ci-revision-demo-") as directory:
        repo = Path(directory)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.name", "Local Demonstration")
        _git(repo, "config", "user.email", "demo@example.invalid")
        (repo / "app").mkdir()
        source = repo / "app" / "example.py"
        source.write_text(
            "import sys\nimport os\n\nprint(os.name, sys.version)\n",
            encoding="utf-8",
        )
        _git(repo, "add", "app/example.py")
        _git(repo, "commit", "-qm", "Deliberately unordered imports for demo")
        failing_revision = _git(repo, "rev-parse", "HEAD")

        # Make the active working tree different from the failing commit.
        source.write_text("print('newer uncommitted code')\n", encoding="utf-8")
        before = source.read_bytes()
        result = preview_committed_import_fix(
            repo, failing_revision, "code_quality", ["app/example.py"], "app/example.py"
        )
        assert result["changed"] is True
        assert source.read_bytes() == before
        print("Target revision:", failing_revision[:12])
        print("Fix preview from the old commit:\n", result["diff"])
        print("Active working tree unchanged:", source.read_bytes() == before)
        print("Tests executed:", result["tests_executed"])
        worktree_listing = _git(repo, "worktree", "list", "--porcelain")
        print("Temporary Git worktrees cleaned:", worktree_listing.count("worktree ") == 1)


if __name__ == "__main__":
    main()
