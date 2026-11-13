"""Safe, local-only remediation previews. No source-tree mutations or shell execution.

This is a disposable-file preview, NOT a container/OS security sandbox. Do not
use it to execute untrusted source code. Human approval is always required.
"""

import argparse
import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOWED_DIRS = frozenset({"app", "tests"})
MAX_FILE_BYTES = 128_000


def remediation_policy(category: str) -> dict:
    """Decide which failure categories may be automatically modified."""
    if category == "code_quality":
        return {
            "mode": "preview_only",
            "allowed_action": "sort_python_imports",
            "reason": "Only import ordering is approved for disposable previews.",
        }
    return {
        "mode": "human_review",
        "allowed_action": None,
        "reason": (
            "Secrets, vulnerabilities, signatures, and other incidents require "
            "human review; no scanner suppressions or credential changes."
        ),
    }


def _safe_python_file(repo: Path, file_path: str) -> tuple[Path, Path]:
    """Validate a relative, regular Python source file inside app/ or tests/."""
    repo = repo.resolve(strict=True)
    rel = Path(file_path)
    if (
        rel.is_absolute()
        or ".." in rel.parts
        or len(rel.parts) < 2
        or rel.parts[0] not in ALLOWED_DIRS
        or rel.suffix != ".py"
    ):
        raise ValueError("Only Python files under app/ or tests/ are permitted")

    source = repo / rel
    # Reject symlinks at every path level, not only at the leaf.
    current = repo
    for component in rel.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("Symlink paths are not permitted")

    if not source.is_file() or not source.resolve().is_relative_to(repo):
        raise ValueError("File not found or outside repository")
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("File too large for automatic preview")
    return source, rel


def preview_import_sort(repo: Path, file_path: str) -> dict:
    """Use Ruff on a temporary file and return a diff; original remains untouched.

    Invokes only the installed Ruff Python module, never a model-provided command.
    Does not run/tests/import the target code. No patch is applied to the repo.
    """
    source, relative = _safe_python_file(Path(repo), file_path)
    original = source.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="ci-remediation-") as directory:
        tmp = Path(directory)
        target = tmp / relative.name
        target.write_text(original, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--isolated", "--fix",
             "--select", "I", "--no-cache", str(target)],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Ruff could not safely prepare an import-only preview "
                f"(exit code {result.returncode})"
            )
        proposed = target.read_text(encoding="utf-8")

    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=f"a/{relative.as_posix()}",
        tofile=f"b/{relative.as_posix()}",
    ))
    return {
        "mode": "preview_only",
        "path": relative.as_posix(),
        "changed": original != proposed,
        "diff": diff,
        "applied_to_repository": False,
        "tests_executed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview safe CI remediation")
    parser.add_argument("--file", help="Python file to preview (app/ or tests/)")
    parser.add_argument("--demo", action="store_true", help="Show a local import-sort demo")
    args = parser.parse_args()
    if args.demo:
        with tempfile.TemporaryDirectory(prefix="ci-remediation-demo-") as directory:
            repo = Path(directory)
            (repo / "app").mkdir()
            demo = repo / "app" / "example.py"
            demo.write_text("import sys\nimport os\n\nprint(os.name, sys.version)\n")
            result = preview_import_sort(repo, "app/example.py")
            print(result["diff"] or "No import-order changes proposed.")
            print("Source unchanged:", demo.read_text().startswith("import sys"))
    elif args.file:
        result = preview_import_sort(Path.cwd(), args.file)
        print(result["diff"] or "No import-order changes proposed.")
        print("Applied to repository: false")
    else:
        parser.error("Specify --demo or --file")


if __name__ == "__main__":
    main()
