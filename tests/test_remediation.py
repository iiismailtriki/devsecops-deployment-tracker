"""Validation of the allowlisted, non-mutating remediation preview."""

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from app.remediation import preview_import_sort, remediation_policy


def test_secret_findings_never_auto_ignored():
    policy = remediation_policy("secret_detection")
    assert policy["mode"] == "human_review"
    assert policy["allowed_action"] is None


def test_code_quality_allows_preview_only():
    policy = remediation_policy("code_quality")
    assert policy["mode"] == "preview_only"
    assert policy["allowed_action"] == "sort_python_imports"


def test_preview_diff_does_not_modify_repository(tmp_path, monkeypatch):
    folder = tmp_path / "app"
    folder.mkdir()
    source = folder / "example.py"
    source.write_text("import sys\nimport os\n")

    def fake_ruff(command, **kwargs):
        assert command[:4] == [
            __import__("sys").executable, "-m", "ruff", "check"
        ]
        Path(command[-1]).write_text("import os\nimport sys\n")
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.remediation.subprocess.run", fake_ruff)
    result = preview_import_sort(tmp_path, "app/example.py")
    assert result["changed"] is True
    assert "+import os" in result["diff"]
    assert "-import os" in result["diff"]
    assert result["applied_to_repository"] is False
    assert result["tests_executed"] is False
    assert source.read_text() == "import sys\nimport os\n"


@pytest.mark.parametrize("path", [
    "../../.ssh/id_rsa", "/etc/passwd", ".env", "README.md",
    "docs/secrets.py", "app/../tests/x.py",
])
def test_rejects_unapproved_paths(tmp_path, path):
    with pytest.raises(ValueError):
        preview_import_sort(tmp_path, path)


def test_rejects_symlink(tmp_path):
    folder = tmp_path / "app"
    folder.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n")
    (folder / "link.py").symlink_to(outside)
    with pytest.raises(ValueError, match="Symlink"):
        preview_import_sort(tmp_path, "app/link.py")


def test_rejects_oversized_file(tmp_path):
    folder = tmp_path / "tests"
    folder.mkdir()
    (folder / "huge.py").write_bytes(b"x" * 129_000)
    with pytest.raises(ValueError, match="large"):
        preview_import_sort(tmp_path, "tests/huge.py")


def test_unknown_incident_is_human_review():
    assert remediation_policy("arbitrary_code_execution")["mode"] == "human_review"
