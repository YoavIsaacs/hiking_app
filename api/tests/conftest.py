import asyncio
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.elevation import new_http_client
from app.config import Settings
from app.main import create_app
from tests.elevation_support import ElevationApi, elevation_mock

if sys.platform == "win32":
    # Windows' default Proactor loop connects with overlapped I/O, which bypasses
    # pytest-socket's guard on socket.connect: a forgotten mock would then reach the
    # real network. The selector loop (the Linux default, so CI) goes through the guard.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


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


@pytest.fixture
def elevation_api(settings: Settings) -> Iterator[ElevationApi]:
    """A respx router standing in for Open-Meteo's /v1/elevation (synthetic by default).

    Any other outbound request fails loudly (respx ``assert_all_mocked``).
    """
    with elevation_mock(settings.open_meteo_base_url) as api:
        yield api


@pytest.fixture
def lifespan_client(
    settings: Settings, elevation_api: ElevationApi
) -> Iterator[TestClient]:
    """The real app run WITH its lifespan, so the elevation client exists (ADR 0005)."""
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def transport_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Callable[[httpx.MockTransport], AbstractContextManager[TestClient]]:
    """The real app, lifespan and all, on a ``MockTransport``.

    No respx: respx pre-reads and decodes every mocked response inside the transport,
    so it cannot show how the client handles Content-Encoding or raw bytes. A
    ``MockTransport`` hands the client the stream a real transport would. The only
    substitution is the transport; ``lifespan`` still builds the client and the
    ``ElevationClient`` from ``settings`` (the seam is ``app.main.new_http_client``).
    """

    @contextmanager
    def run(transport: httpx.MockTransport) -> Iterator[TestClient]:
        def build(s: Settings) -> httpx.AsyncClient:
            http = new_http_client(s)
            http._transport = transport  # noqa: SLF001  # keep headers/timeouts, swap wire
            return http

        monkeypatch.setattr("app.main.new_http_client", build)
        with TestClient(create_app(settings)) as c:
            yield c

    return run
