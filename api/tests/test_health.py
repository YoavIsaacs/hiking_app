from fastapi.testclient import TestClient

from app.config import Settings


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_has_version_and_sha(client: TestClient, settings: Settings) -> None:
    body = client.get("/health").json()

    assert body == {
        "status": "ok",
        "version": "9.9.9-test",
        "git_sha": "abc1234test",
        "env": "test",
    }
    assert body["version"] == settings.version
    assert body["git_sha"] == settings.git_sha
