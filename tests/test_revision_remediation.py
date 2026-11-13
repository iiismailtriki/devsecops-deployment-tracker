"""Tests for SHA-pinned, preview-only remediation."""

import subprocess
from pathlib import Path

import pytest

from app import revision_remediation as rr


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
        timeout=15,
    )
    return result.stdout.strip()


@pytest.fixture
def committed_repo(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Example User")
    git(repo, "config", "user.email", "example@example.invalid")
    (repo / "app").mkdir()
    file = repo / "app" / "sample.py"
    file.write_text("import sys\nimport os\n")
    git(repo, "add", "app/sample.py")
    git(repo, "commit", "-qm", "First commit")
    revision = git(repo, "rev-parse", "HEAD")
    file.write_text("# modified active working tree\n")
    return repo, revision, file


def test_uses_exact_failing_commit_not_active_files(committed_repo, monkeypatch):
    repo, revision, file = committed_repo
    observed = []

    def fake_preview(checkout, path):
        content = (checkout / path).read_text()
        observed.append(content)
        assert "import sys" in content
        assert "modified active" not in content
        return {"path": path, "changed": True, "diff": "synthetic patch"}

    monkeypatch.setattr(rr, "preview_import_sort", fake_preview)
    result = rr.preview_committed_import_fix(
        repo, revision, "code_quality", ["app/sample.py"], "app/sample.py"
    )
    assert result["changed"] is True
    assert result["diff"] == "synthetic patch"
    assert result["tests_executed"] is False
    assert file.read_text() == "# modified active working tree\n"
    assert len(observed) == 1
    assert git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1


@pytest.mark.parametrize(
    "category", ["secret_detection", "container_vulnerability", "unknown"]
)
def test_security_and_unknown_categories_are_blocked(committed_repo, category):
    repo, revision, _ = committed_repo
    result = rr.preview_committed_import_fix(
        repo, revision, category, ["app/sample.py"], "app/sample.py"
    )
    assert "error" in result


@pytest.mark.parametrize(
    "bad_path",
    [
        "../app/sample.py",
        "/etc/passwd",
        "app/.hidden.py",
        "docs/file.py",
        "app/sample.py/other",
        "app/link//file.py",
    ],
)
def test_unapproved_paths_blocked(committed_repo, bad_path):
    repo, revision, _ = committed_repo
    result = rr.preview_committed_import_fix(
        repo, revision, "code_quality", [bad_path], bad_path
    )
    assert "error" in result


def test_file_must_be_named_by_diagnostic(committed_repo):
    repo, revision, _ = committed_repo
    result = rr.preview_committed_import_fix(
        repo, revision, "code_quality", ["tests/test_other.py"], "app/sample.py"
    )
    assert "error" in result


@pytest.mark.parametrize(
    "bad_revision", ["HEAD", "main", "a" * 39, "not-a-commit", "a" * 41]
)
def test_requires_full_commit_sha(committed_repo, bad_revision):
    repo, _, _ = committed_repo
    result = rr.preview_committed_import_fix(
        repo, bad_revision, "code_quality", ["app/sample.py"], "app/sample.py"
    )
    assert "error" in result


def test_removed_revision_is_not_fetched(committed_repo):
    repo, _, _ = committed_repo
    with pytest.raises(RuntimeError, match="Git operation failed"):
        rr.preview_committed_import_fix(
            repo, "0" * 40, "code_quality", ["app/sample.py"], "app/sample.py"
        )


def test_symlink_at_failing_revision_rejected(tmp_path, monkeypatch):
    repo = tmp_path / "symlinkrepo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Example User")
    git(repo, "config", "user.email", "example@example.invalid")
    (repo / "app").mkdir()
    (repo / "app" / "sample.py").symlink_to("/etc/passwd")
    git(repo, "add", "app/sample.py")
    git(repo, "commit", "-qm", "Symlink file")
    revision = git(repo, "rev-parse", "HEAD")

    # Use the actual guard from the existing remediation module; never execute
    # target code and never call Ruff for a symlink.
    from app.remediation import _safe_python_file

    monkeypatch.setattr(
        rr, "preview_import_sort", lambda checkout, p: _safe_python_file(checkout, p)
    )
    with pytest.raises(ValueError, match="Symlink"):
        rr.preview_committed_import_fix(
            repo, revision, "code_quality", ["app/sample.py"], "app/sample.py"
        )
    assert git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
