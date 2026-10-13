import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_SHA", "envsha999")
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setenv("CORS_ORIGINS", '["http://one.test", "http://two.test"]')

    settings = Settings(_env_file=None)

    assert settings.git_sha == "envsha999"
    assert settings.env == "staging"
    assert settings.cors_origins == ["http://one.test", "http://two.test"]


def test_create_app_without_args_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_SHA", "fromenv123")
    monkeypatch.setenv("ENV", "staging")

    body = TestClient(create_app()).get("/health").json()

    assert body["git_sha"] == "fromenv123"
    assert body["env"] == "staging"
