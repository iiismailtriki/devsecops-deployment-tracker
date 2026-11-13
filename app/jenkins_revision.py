"""Fail-closed Jenkins Git-revision attestation for a previously listed failed build.

Only queries authenticated local Jenkins and checks the full commit exists in the
local Git object database. Never fetches, checks out, executes code, or edits Git.
"""

import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests

from app.jenkins_client import BASE_URL, PIPELINE

SHA_40 = re.compile(r"[0-9a-fA-F]{40}\Z")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")


def read_failed_build_revision(client, build: dict, repo: Path) -> dict:
    """Return a verified full SHA, or an unavailable result; never guess a SHA.

    The build must come from the Jenkins failed-build allowlist, not LLM input.
    Jenkins `lastBuiltRevision` is authoritative for *that build*, not a
    guarantee of repository provenance across untrusted Jenkins controllers.
    """
    unavailable = {"status": "unavailable"}
    if not isinstance(build, dict):
        return unavailable

    branch, number, build_url = (
        build.get("branch"), build.get("number"), build.get("url")
    )
    if (
        not isinstance(branch, str)
        or BRANCH.fullmatch(branch) is None
        or type(number) is not int
        or number <= 0
        or not isinstance(build_url, str)
    ):
        return unavailable

    try:
        url = urlsplit(build_url)
        expected_path = (
            f"/job/{quote(PIPELINE, safe='')}/job/{quote(branch, safe='')}/{number}/"
        )
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "localhost"}
            or url.port != 8080
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path != expected_path
        ):
            return unavailable
        # Make the outbound request to a fixed local endpoint, not an
        # arbitrary build URL supplied by a model or a Jenkins response.
        response = client.session.get(
            f"{BASE_URL}{expected_path}api/json",
            params={"tree": "number,result,actions[lastBuiltRevision[SHA1]]"},
            timeout=10,
            allow_redirects=False,
        )
        if response.status_code != 200:
            return unavailable
        data = response.json()
        if (
            not isinstance(data, dict)
            or data.get("number") != number
            or data.get("result") != "FAILURE"
        ):
            return unavailable
        revisions = set()
        for action in data.get("actions", []):
            if not isinstance(action, dict):
                continue
            revision = action.get("lastBuiltRevision")
            if not isinstance(revision, dict):
                continue
            sha = revision.get("SHA1")
            if isinstance(sha, str) and SHA_40.fullmatch(sha):
                revisions.add(sha.lower())
        if len(revisions) != 1:
            return unavailable
        sha = next(iter(revisions))
        checked = subprocess.run(
            ["git", "-C", str(Path(repo).resolve()), "rev-parse", "--verify", f"{sha}^{{commit}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if checked.returncode != 0 or checked.stdout.strip().lower() != sha:
            return unavailable
        return {"status": "verified", "commit": sha, "source": "jenkins_lastBuiltRevision"}
    except (AttributeError, ValueError, TypeError, OSError, subprocess.TimeoutExpired, requests.RequestException):
        return unavailable
