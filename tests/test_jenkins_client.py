import pytest

from app.jenkins_client import JenkinsClient


class FakeResponse:
    status_code = 200

    def __init__(self, payload=None, chunks=None):
        self.payload = payload or {}
        self.chunks = chunks or []

    def json(self):
        return self.payload

    def iter_content(self, chunk_size=8192):
        yield from self.chunks

    def close(self):
        pass


def test_discovers_failed_builds(monkeypatch):
    client = JenkinsClient("test-user", "fake-token")
    response = FakeResponse({
        "jobs": [
            {
                "name": "main",
                "lastFailedBuild": None,
            },
            {
                "name": "PR-3",
                "lastFailedBuild": {
                    "number": 1,
                    "url": (
                        "http://localhost:8080/job/"
                        "deployment-tracker-multibranch/job/PR-3/1/"
                    ),
                },
            },
        ]
    })

    monkeypatch.setattr(
        client.session, "get", lambda *args, **kwargs: response
    )

    builds = client.failed_builds()
    assert len(builds) == 1
    assert builds[0]["branch"] == "PR-3"


def test_rejects_untrusted_build_url():
    client = JenkinsClient("test-user", "fake-token")

    with pytest.raises(ValueError):
        client.console_log("https://example.com/steal-token")


def test_reads_realistic_failure_log(monkeypatch):
    client = JenkinsClient("test-user", "fake-token")
    response = FakeResponse(chunks=[
        b"Trivy found vulnerability CVE-2026-12345\n",
        b"Finished: FAILURE\n",
    ])
    monkeypatch.setattr(
        client.session, "get", lambda *args, **kwargs: response
    )

    log, truncated = client.console_log(
        "http://localhost:8080/job/"
        "deployment-tracker-multibranch/job/main/2/"
    )

    assert "Finished: FAILURE" in log
    assert truncated is False


def test_limits_download_size(monkeypatch):
    client = JenkinsClient("test-user", "fake-token")
    response = FakeResponse(chunks=[b"x" * 1_000_100])
    monkeypatch.setattr(
        client.session, "get", lambda *args, **kwargs: response
    )

    log, truncated = client.console_log(
        "http://localhost:8080/job/"
        "deployment-tracker-multibranch/job/main/2/"
    )
    assert truncated is True
    assert len(log) <= 200_000
