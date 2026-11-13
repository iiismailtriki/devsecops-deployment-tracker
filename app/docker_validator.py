"""Bounded Docker/Ruff validation of a proposed Python import-order correction.

Validation executes only the Ruff binary, not application code. Docker is an
additional restriction layer, not a guarantee of malicious-code isolation.
This module does not generate or apply patches, modify the repo, or call an LLM.
"""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

IMAGE = "devsecops-jenkins-agent:0.3"
MAX_SOURCE_BYTES = 128_000


def validate_imports_in_docker(source_text: str, ruff_binary: Path) -> dict:
    """Check a candidate file's import ordering inside a restricted container.

    Caller must independently pin and authorize the source revision. Never give
    Docker the repository, API keys, or host Docker socket as a mount.
    """
    if not isinstance(source_text, str):
        raise TypeError("source_text must be a string")
    encoded = source_text.encode("utf-8")
    if not encoded or len(encoded) > MAX_SOURCE_BYTES or b"\x00" in encoded:
        raise ValueError("Invalid or oversized Python source")
    ruff_binary = Path(ruff_binary).resolve(strict=True)
    if not ruff_binary.is_file() or not os.access(ruff_binary, os.X_OK):
        raise ValueError("Ruff executable is unavailable")

    with tempfile.TemporaryDirectory(prefix="ci-ruff-docker-") as directory:
        candidate = Path(directory) / "candidate.py"
        candidate.write_bytes(encoded)
        candidate.chmod(0o644)  # Readable by non-root UID in the container.

        command = [
            "docker", "run", "--rm", "--pull", "never",
            "--network", "none", "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,noexec,size=64m,mode=1777",
            "--user", "10001:10001", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--memory", "512m", "--cpus", "1",
            "--mount", (
                f"type=bind,src={ruff_binary},"
                "dst=/usr/local/bin/ruff,readonly"
            ),
            "--mount", (
                f"type=bind,src={candidate},dst=/tmp/candidate.py,readonly"
            ),
            "--entrypoint", "/usr/local/bin/ruff",
            IMAGE, "check", "--isolated", "--no-cache", "--select", "I",
            "/tmp/candidate.py",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                timeout=35, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {
                "status": "unavailable", "passed": False,
                "tests_executed": False, "source_changed": False,
            }

        status = {0: "passed", 1: "failed"}.get(result.returncode, "unavailable")
        return {
            "status": status,
            "passed": status == "passed",
            "tests_executed": status in {"passed", "failed"},
            "source_changed": False,
            "validation": "ruff_imports_only",
            "network_disabled": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Restricted Docker import validation")
    parser.add_argument("--demo", action="store_true", help="Run a local pass/fail demonstration")
    args = parser.parse_args()
    if not args.demo:
        parser.error("Use --demo; build-revision integration comes next")
    ruff = Path.cwd() / ".venv/bin/ruff"
    good = "import os\nimport sys\n\nprint(os.name, sys.version)\n"
    bad = "import sys\nimport os\n\nprint(os.name, sys.version)\n"
    valid = validate_imports_in_docker(good, ruff)
    invalid = validate_imports_in_docker(bad, ruff)
    print("Corrected candidate:", valid["status"])
    print("Uncorrected candidate:", invalid["status"])
    print("Source files modified: False")
    if valid["status"] != "passed" or invalid["status"] != "failed":
        raise SystemExit("Validation demo did not produce expected results")
    print("DOCKER VALIDATION DEMO PASSED")


if __name__ == "__main__":
    main()
