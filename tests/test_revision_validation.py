"""Commit-pinned candidate reconstruction and Docker-validation contract tests."""

import difflib
import subprocess

from app import revision_validation as rv

OLD = "import sys\nimport os\n\nprint(os.name, sys.version)\n"
NEW = "import os\nimport sys\n\nprint(os.name, sys.version)\n"


def fixture_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@example.invalid"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (repo / "app").mkdir()
    source = repo / "app/example.py"
    source.write_text(OLD)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True
    )
    sha = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    source.write_text("# modified live file\n")
    return repo, sha, source


def fake_ruff(tmp_path):
    executable = tmp_path / "mock-ruff"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\nfrom pathlib import Path\n"
        "f = Path(sys.argv[-1])\n"
        "f.write_text(f.read_text().replace('import sys\\nimport os', 'import os\\nimport sys'))\n"
    )
    executable.chmod(0o755)
    return executable


def mock_preview(monkeypatch, sha, diff=None):
    if diff is None:
        diff = "".join(difflib.unified_diff(
            OLD.splitlines(keepends=True), NEW.splitlines(keepends=True),
            fromfile="a/app/example.py", tofile="b/app/example.py",
        ))
    monkeypatch.setattr(
        rv, "preview_committed_import_fix",
        lambda *_args: {
            "commit": sha, "path": "app/example.py", "changed": True,
            "diff": diff,
        },
    )


def test_exact_commit_correction_is_validated_and_live_tree_unchanged(
    tmp_path, monkeypatch
):
    repo, sha, source = fixture_repo(tmp_path)
    mock_preview(monkeypatch, sha)
    ruff = fake_ruff(tmp_path)
    received = []

    def fake_docker(candidate, binary):
        received.append((candidate, binary))
        return {"status": "passed", "tests_executed": True}

    monkeypatch.setattr(rv, "validate_imports_in_docker", fake_docker)
    result = rv.validate_pinned_import_fix(
        repo, sha, "code_quality", ["app/example.py"], "app/example.py", ruff
    )
    assert result["status"] == "validated"
    assert result["docker_result"] == "passed"
    assert result["application_tests_executed"] is False
    assert received == [(NEW, ruff.resolve())]
    assert source.read_text() == "# modified live file\n"


def test_docker_failure_is_reported_without_modifications(tmp_path, monkeypatch):
    repo, sha, source = fixture_repo(tmp_path)
    mock_preview(monkeypatch, sha)
    monkeypatch.setattr(rv, "validate_imports_in_docker", lambda *_: {
        "status": "failed", "tests_executed": True,
    })
    result = rv.validate_pinned_import_fix(
        repo, sha, "code_quality", ["app/example.py"],
        "app/example.py", fake_ruff(tmp_path),
    )
    assert result["status"] == "failed"
    assert source.read_text() == "# modified live file\n"


def test_docker_unavailable_never_claims_success(tmp_path, monkeypatch):
    repo, sha, _ = fixture_repo(tmp_path)
    mock_preview(monkeypatch, sha)
    monkeypatch.setattr(rv, "validate_imports_in_docker", lambda *_: {
        "status": "unavailable", "tests_executed": False,
    })
    result = rv.validate_pinned_import_fix(
        repo, sha, "code_quality", ["app/example.py"],
        "app/example.py", fake_ruff(tmp_path),
    )
    assert result["status"] == "unavailable"
    assert result["import_check_executed"] is False


def test_preview_mismatch_refuses_docker(tmp_path, monkeypatch):
    repo, sha, _ = fixture_repo(tmp_path)
    mock_preview(monkeypatch, sha, diff="TAMPERED PATCH")
    monkeypatch.setattr(rv, "validate_imports_in_docker", lambda *_: (
        (_ for _ in ()).throw(AssertionError("must not validate mismatched diff"))
    ))
    result = rv.validate_pinned_import_fix(
        repo, sha, "code_quality", ["app/example.py"],
        "app/example.py", fake_ruff(tmp_path),
    )
    assert result["status"] == "unavailable"
    assert result["validation"] == "preview_mismatch"


def test_preview_denial_refuses_candidate_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rv, "preview_committed_import_fix", lambda *_: {"error": "invalid revision"}
    )
    result = rv.validate_pinned_import_fix(
        tmp_path, "0" * 40, "secret_detection", ["app/example.py"],
        "app/example.py", tmp_path / "ruff",
    )
    assert result == {"status": "blocked", "error": "Pinned preview refused"}


def test_no_change_skips_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "preview_committed_import_fix", lambda *_: {
        "commit": "a" * 40, "path": "app/example.py", "changed": False,
    })
    monkeypatch.setattr(rv, "validate_imports_in_docker", lambda *_: (
        (_ for _ in ()).throw(AssertionError("must not run Docker"))
    ))
    result = rv.validate_pinned_import_fix(
        tmp_path, "a" * 40, "code_quality", ["app/example.py"],
        "app/example.py", tmp_path / "ruff",
    )
    assert result["status"] == "no_change"


def test_missing_ruff_fails_closed(tmp_path, monkeypatch):
    repo, sha, _ = fixture_repo(tmp_path)
    mock_preview(monkeypatch, sha)
    result = rv.validate_pinned_import_fix(
        repo, sha, "code_quality", ["app/example.py"],
        "app/example.py", tmp_path / "missing-ruff",
    )
    assert result["status"] == "unavailable"
    assert result["validation"] == "ruff_missing"
