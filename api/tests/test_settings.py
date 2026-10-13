import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

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


def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_malformed_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://not-json.test")

    with pytest.raises(SettingsError):
        Settings(_env_file=None)
