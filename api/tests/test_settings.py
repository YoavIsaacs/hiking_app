from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

from app.config import Settings
from app.main import create_app


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIKE_GIT_SHA", "envsha999")
    monkeypatch.setenv("HIKE_ENV", "staging")
    monkeypatch.setenv("HIKE_CORS_ORIGINS", '["http://one.test", "http://two.test"]')

    settings = Settings(_env_file=None)

    assert settings.git_sha == "envsha999"
    assert settings.env == "staging"
    assert settings.cors_origins == ["http://one.test", "http://two.test"]


def test_create_app_without_args_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIKE_GIT_SHA", "fromenv123")
    monkeypatch.setenv("HIKE_ENV", "staging")

    body = TestClient(create_app()).get("/health").json()

    assert body["git_sha"] == "fromenv123"
    assert body["env"] == "staging"


def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIKE_LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_malformed_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIKE_CORS_ORIGINS", "http://not-json.test")

    with pytest.raises(SettingsError):
        Settings(_env_file=None)


def test_settings_read_every_hike_prefixed_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIKE_VERSION", "1.2.3")
    monkeypatch.setenv("HIKE_OPEN_METEO_BASE_URL", "http://meteo.test")
    monkeypatch.setenv("HIKE_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("HIKE_CORS_FIREBASE_SITE", "hike-prep-abc")

    settings = Settings(_env_file=None)

    assert settings.version == "1.2.3"
    assert settings.open_meteo_base_url == "http://meteo.test"
    assert settings.log_level == "DEBUG"
    assert settings.model_dump().get("cors_firebase_site") == "hike-prep-abc"


def test_cors_defaults_are_localhost_and_no_firebase_site() -> None:
    dumped = Settings(_env_file=None).model_dump()

    assert dumped["cors_origins"] == ["http://localhost:5173"]
    assert dumped.get("cors_firebase_site", "<missing field>") is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ENV", "staging"),
        ("VERSION", "9.9.9"),
        ("GIT_SHA", "shellvalue"),
        ("CORS_ORIGINS", '["http://x.test"]'),
        ("OPEN_METEO_BASE_URL", "http://meteo.test"),
    ],
)
def test_unprefixed_env_names_are_ignored(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    settings = Settings(_env_file=None)

    assert settings.env == "local"
    assert settings.version == "0.0.0-dev"
    assert settings.git_sha == "unknown"
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.open_meteo_base_url == "https://api.open-meteo.com"


def test_unprefixed_invalid_log_level_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    assert Settings(_env_file=None).log_level == "INFO"


def test_unprefixed_env_has_no_effect_on_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setenv("GIT_SHA", "shellvalue")
    monkeypatch.setenv("VERSION", "9.9.9")

    body = TestClient(create_app()).get("/health").json()

    assert body["env"] == "local"
    assert body["git_sha"] == "unknown"


def test_dotenv_reads_prefixed_keys_and_ignores_unprefixed(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "HIKE_GIT_SHA=fromdotenv\nHIKE_ENV=dotenv-env\nVERSION=7.7.7\nGIT_SHA=bare\nENV=bare\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=dotenv)

    assert settings.git_sha == "fromdotenv"
    assert settings.env == "dotenv-env"
    assert settings.version == "0.0.0-dev"


def test_invalid_hike_cors_origin_in_env_fails_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIKE_CORS_ORIGINS", '["http://x.test/path"]')

    with pytest.raises(ValueError):
        create_app(Settings(_env_file=None))
