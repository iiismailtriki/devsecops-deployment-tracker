"""No live API or credentials required for revision-reader tests."""

import subprocess

from app.jenkins_revision import read_failed_build_revision


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload, status_code=200):
        self.response = FakeResponse(payload, status_code)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class FakeClient:
    def __init__(self, payload, status_code=200):
        self.session = FakeSession(payload, status_code)


def _build():
    return {
        "branch": "PR-3",
        "number": 1,
        "url": "http://localhost:8080/job/deployment-tracker-multibranch/job/PR-3/1/",
    }


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README").write_text("safe\n")
    subprocess.run(["git", "-C", str(repo), "add", "README"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "test"],
        check=True,
    )
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    return repo, sha


def test_verified_revision_from_failed_build(tmp_path):
    repo, sha = _repo(tmp_path)
    client = FakeClient({"number": 1, "result": "FAILURE", "actions": [{"lastBuiltRevision": {"SHA1": sha}}]})
    result = read_failed_build_revision(client, _build(), repo)
    assert result == {"status": "verified", "commit": sha, "source": "jenkins_lastBuiltRevision"}
    url, kwargs = client.session.calls[0]
    assert url.endswith("/job/PR-3/1/api/json")
    assert kwargs["allow_redirects"] is False


def test_rejects_successful_build(tmp_path):
    repo, sha = _repo(tmp_path)
    client = FakeClient({"number": 1, "result": "SUCCESS", "actions": [{"lastBuiltRevision": {"SHA1": sha}}]})
    assert read_failed_build_revision(client, _build(), repo)["status"] == "unavailable"


def test_rejects_conflicting_metadata(tmp_path):
    repo, sha = _repo(tmp_path)
    other = "f" * 40 if sha != "f" * 40 else "e" * 40
    client = FakeClient({"number": 1, "result": "FAILURE", "actions": [
        {"lastBuiltRevision": {"SHA1": sha}}, {"lastBuiltRevision": {"SHA1": other}},
    ]})
    assert read_failed_build_revision(client, _build(), repo)["status"] == "unavailable"


def test_rejects_unknown_local_revision(tmp_path):
    repo, sha = _repo(tmp_path)
    other = "f" * 40 if sha != "f" * 40 else "e" * 40
    client = FakeClient({"number": 1, "result": "FAILURE", "actions": [{"lastBuiltRevision": {"SHA1": other}}]})
    assert read_failed_build_revision(client, _build(), repo)["status"] == "unavailable"


def test_rejects_untrusted_build_url_without_request(tmp_path):
    repo, sha = _repo(tmp_path)
    client = FakeClient({"number": 1, "result": "FAILURE", "actions": [{"lastBuiltRevision": {"SHA1": sha}}]})
    build = _build()
    build["url"] = "https://attacker.example/job/deployment-tracker-multibranch/job/PR-3/1/"
    assert read_failed_build_revision(client, build, repo)["status"] == "unavailable"
    assert client.session.calls == []


def test_rejects_wrong_build_number(tmp_path):
    repo, sha = _repo(tmp_path)
    client = FakeClient({"number": 2, "result": "FAILURE", "actions": [{"lastBuiltRevision": {"SHA1": sha}}]})
    assert read_failed_build_revision(client, _build(), repo)["status"] == "unavailable"


def test_rejects_missing_session_and_no_api_calls(tmp_path):
    repo, _ = _repo(tmp_path)
    class MissingSession:
        pass
    assert read_failed_build_revision(MissingSession(), _build(), repo)["status"] == "unavailable"


def test_rejects_bool_build_number(tmp_path):
    repo, sha = _repo(tmp_path)
    client = FakeClient({"number": True, "result": "FAILURE", "actions": [{"lastBuiltRevision": {"SHA1": sha}}]})
    build = _build()
    build["number"] = True
    assert read_failed_build_revision(client, build, repo)["status"] == "unavailable"
    assert client.session.calls == []
