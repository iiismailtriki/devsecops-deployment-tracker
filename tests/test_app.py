import pytest

from app.main import create_app


@pytest.fixture
def client():
    """Create a Flask test client for each test."""

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as test_client:
        yield test_client


def test_home(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {
        "service": "deployment-tracker",
        "status": "running",
    }


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "healthy",
    }


def test_version(client, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "0.1.0")
    monkeypatch.setenv("BUILD_NUMBER", "test-build")
    monkeypatch.setenv("GIT_COMMIT", "abc1234")

    response = client.get("/version")

    assert response.status_code == 200

    data = response.get_json()

    assert data["version"] == "0.1.0"
    assert data["build_number"] == "test-build"
    assert data["git_commit"] == "abc1234"


def test_info(client, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "0.1.0")
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("BUILD_NUMBER", "test-build")
    monkeypatch.setenv("GIT_COMMIT", "abc1234")

    response = client.get("/info")

    assert response.status_code == 200

    data = response.get_json()

    assert data["service"] == "deployment-tracker"
    assert data["status"] == "running"
    assert data["version"] == "0.1.0"
    assert data["environment"] == "testing"
    assert data["build_number"] == "test-build"
    assert data["git_commit"] == "abc1234"


def test_unknown_route_returns_404(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
def test_version_uses_default_values(client, monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.delenv("BUILD_NUMBER", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)

    response = client.get("/version")

    assert response.status_code == 200

    data = response.get_json()

    assert data["version"] == "dev"
    assert data["build_number"] == "local"
    assert data["git_commit"] == "unknown"
