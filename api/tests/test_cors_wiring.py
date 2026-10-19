"""CORS through the real app (ADR 0002 section 7): create_app to response headers."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ACAO = "access-control-allow-origin"
SITE = "hike-prep-abc"
OTHER = "other-project-xyz"
PREVIEW = f"https://{SITE}--pr-12-abc123.web.app"


def _settings(**values: object) -> Settings:
    # model_validate: the typed constructor lacks the new fields until the build step.
    return Settings.model_validate({"env": "production", **values})


@pytest.fixture
def prod_client() -> TestClient:
    return TestClient(create_app(_settings(cors_origins=[], cors_firebase_site=SITE)))


def _simple(client: TestClient, origin: str) -> dict[str, str]:
    return dict(client.get("/health", headers={"Origin": origin}).headers)


def _preflight(client: TestClient, origin: str) -> dict[str, str]:
    response = client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    return dict(response.headers)


@pytest.mark.parametrize(
    "origin",
    [
        f"https://{SITE}.web.app",
        f"https://{SITE}.firebaseapp.com",
        PREVIEW,
        f"https://{SITE}--pr-7-a1b2c3d4.web.app",
    ],
)
def test_production_origins_get_acao_on_simple_and_preflight(
    prod_client: TestClient, origin: str
) -> None:
    assert _simple(prod_client, origin).get(ACAO) == origin
    assert _preflight(prod_client, origin).get(ACAO) == origin


@pytest.mark.parametrize(
    "origin",
    [
        f"https://{SITE}.web.app.evil.com",
        f"https://evil{SITE}.web.app",
        f"https://x-{SITE}--pr-1-abc123.web.app",
        f"http://{SITE}.web.app",
        f"https://{SITE}.web.app:8443",
        f"https://{SITE}.web.app/",
        f"https://{SITE}--pr-1-abc123.firebaseapp.com",
        f"https://{SITE}--feature-abc123.web.app",
        f"https://{SITE}--pr-1-abc123.web.app.evil.com",
        f"https://{SITE}--pr-1-ABC123.web.app",
        "null",
        "http://localhost:5173",
        f"https://{OTHER}--pr-1-abc123.web.app",
    ],
)
def test_lookalike_origins_get_no_acao(prod_client: TestClient, origin: str) -> None:
    assert ACAO not in _simple(prod_client, origin)
    assert ACAO not in _preflight(prod_client, origin)


def test_preview_origin_is_rejected_when_no_site_is_configured() -> None:
    client = TestClient(create_app(_settings(cors_origins=["http://localhost:5173"])))

    assert ACAO not in _simple(client, PREVIEW)
    assert _simple(client, "http://localhost:5173").get(ACAO) == "http://localhost:5173"


def test_configured_exact_origins_still_work_alongside_the_site() -> None:
    client = TestClient(
        create_app(
            _settings(cors_origins=["https://custom.test"], cors_firebase_site=SITE)
        )
    )

    assert _simple(client, "https://custom.test").get(ACAO) == "https://custom.test"
    assert _simple(client, PREVIEW).get(ACAO) == PREVIEW


def test_create_app_reads_cors_from_hike_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIKE_CORS_ORIGINS", "[]")
    monkeypatch.setenv("HIKE_CORS_FIREBASE_SITE", SITE)

    client = TestClient(create_app())

    assert _simple(client, PREVIEW).get(ACAO) == PREVIEW
    assert ACAO not in _simple(client, "http://localhost:5173")


@pytest.mark.parametrize("site", ["my--site-x", "Hike-prep", "abcde", "abcdef\n", ""])
def test_create_app_fails_at_startup_on_an_invalid_site(site: str) -> None:
    with pytest.raises(ValueError):
        create_app(_settings(cors_origins=[], cors_firebase_site=site))


@pytest.mark.parametrize("origin", ["*", "http://x.test/", "http://x.test/path"])
def test_create_app_fails_at_startup_on_an_invalid_origin(origin: str) -> None:
    with pytest.raises(ValueError):
        create_app(_settings(cors_origins=[origin]))


def test_invalid_env_values_fail_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIKE_CORS_FIREBASE_SITE", "bad--site")

    with pytest.raises(ValueError):
        create_app()
