import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Settings with explicit, distinctive values; never reads the real env or .env."""
    return Settings(
        _env_file=None,
        env="test",
        cors_origins=["http://allowed.test"],
        version="9.9.9-test",
        git_sha="abc1234test",
        open_meteo_base_url="http://open-meteo.test",
        log_level="INFO",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
