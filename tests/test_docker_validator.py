"""Docker validator unit tests use a fake Docker process; no daemon required."""

import subprocess
from pathlib import Path

import pytest

from app import docker_validator


@pytest.fixture
def fake_ruff(tmp_path):
    tool = tmp_path / "ruff"
    tool.write_text("fixture")
    tool.chmod(0o755)
    return tool


@pytest.mark.parametrize(("returncode", "status", "executed"), [
    (0, "passed", True), (1, "failed", True), (2, "unavailable", False),
])
def test_validation_result(monkeypatch, fake_ruff, returncode, status, executed):
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, returncode, "", "")

    monkeypatch.setattr(docker_validator.subprocess, "run", fake_run)
    result = docker_validator.validate_imports_in_docker("import os\n", fake_ruff)
    assert result["status"] == status
    assert result["tests_executed"] is executed
    assert result["source_changed"] is False
    assert "--network" in seen["args"]
    assert seen["args"][seen["args"].index("--network") + 1] == "none"
    assert "--read-only" in seen["args"]
    assert "--cap-drop" in seen["args"]
    assert "--pull" in seen["args"]
    assert seen["args"][seen["args"].index("--pull") + 1] == "never"
    assert seen["kwargs"]["timeout"] == 35
    assert not any("docker.sock" in arg for arg in seen["args"])
    assert not any("/home/" in arg and "src=" not in arg for arg in seen["args"])


def test_rejects_non_string(fake_ruff):
    with pytest.raises(TypeError):
        docker_validator.validate_imports_in_docker(None, fake_ruff)


def test_rejects_bad_source(fake_ruff):
    for value in ("", "abc\x00def", "x" * 128_001):
        with pytest.raises(ValueError):
            docker_validator.validate_imports_in_docker(value, fake_ruff)


def test_rejects_missing_ruff(tmp_path):
    with pytest.raises(FileNotFoundError):
        docker_validator.validate_imports_in_docker("import os\n", tmp_path / "missing")


def test_docker_timeout(monkeypatch, fake_ruff):
    def fake_run(args, **_kwargs):
        raise subprocess.TimeoutExpired(args, 35)

    monkeypatch.setattr(docker_validator.subprocess, "run", fake_run)
    result = docker_validator.validate_imports_in_docker("import os\n", fake_ruff)
    assert result["status"] == "unavailable"
    assert result["tests_executed"] is False


def test_source_is_only_temp_file(monkeypatch, fake_ruff):
    def fake_run(args, **_kwargs):
        mounts = [args[index + 1] for index, value in enumerate(args) if value == "--mount"]
        source_mounts = [mount for mount in mounts if "candidate.py" in mount]
        assert len(source_mounts) == 1
        assert "dst=/tmp/candidate.py,readonly" in source_mounts[0]
        candidate_path = Path(source_mounts[0].split("src=", 1)[1].split(",", 1)[0])
        assert candidate_path.read_text() == "import os\n"
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(docker_validator.subprocess, "run", fake_run)
    result = docker_validator.validate_imports_in_docker("import os\n", fake_ruff)
    assert result["passed"] is True
