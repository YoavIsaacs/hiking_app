"""The upload is closed right after ``read()`` (ADR 0004 3.10, item 19).

A request that waits for the parse slot must hold only the ``bytes`` it read, not
Starlette's spool as well. Through the real wiring: ``create_app`` -> router ->
``parse_route``. Only the pure pipeline is replaced by a stub that records whether the
request's ``UploadFile`` was already closed when it ran.
"""

import threading
from collections.abc import AsyncIterator, Callable

import anyio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

import app.routers.routes as routes_module
from app.body_limit import too_large
from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.models.route import RouteSummary
from app.routes.params import MAX_UPLOAD_BYTES, ParseParams
from app.routes.summary import summarise_gpx
from tests.routes.gpx_builders import gpx_bytes, out_and_back
from tests.routes.http_helpers import URL, assert_error, padded_to

VALID = gpx_bytes([out_and_back()])


class Spy:
    """Records every UploadFile that ``parse_route`` reads and what the parse saw."""

    def __init__(self) -> None:
        self.uploads: list[UploadFile] = []
        self.closed_at_parse: list[bool] = []
        self.closed_at_413: list[bool] = []
        self.release = threading.Event()
        self.calls = 0

    def all_closed(self) -> bool:
        return bool(self.uploads) and all(u.file.closed for u in self.uploads)

    def summarise(
        self, data: bytes, filename: str | None, params: ParseParams | None = None
    ) -> RouteSummary:
        self.calls += 1
        self.closed_at_parse.append(self.all_closed())
        if filename == "hold.gpx" and not self.release.wait(timeout=15):
            raise RuntimeError("the test never released the parse")
        return summarise_gpx(data, filename)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    spy = Spy()
    original_read = UploadFile.read

    async def recording_read(self: UploadFile, size: int = -1) -> bytes:
        spy.uploads.append(self)
        return await original_read(self, size)

    def recording_too_large() -> ApiError:
        spy.closed_at_413.append(spy.all_closed())
        return too_large()

    monkeypatch.setattr(UploadFile, "read", recording_read)
    monkeypatch.setattr(routes_module, "summarise_gpx", spy.summarise)
    monkeypatch.setattr(routes_module, "too_large", recording_too_large)
    return spy


def test_the_upload_is_closed_before_the_parse_runs(
    spy: Spy, client: TestClient
) -> None:
    response = client.post(URL, files={"file": ("r.gpx", VALID, "application/gpx+xml")})
    assert response.status_code == 200, response.text
    assert len(spy.uploads) == 1
    assert spy.closed_at_parse == [True]


def test_the_upload_is_closed_before_a_413_from_the_exact_length_check(
    spy: Spy, client: TestClient
) -> None:
    """Layer 3: the body cap lets MAX + 1 file bytes through, the read check refuses."""
    data = padded_to(VALID, MAX_UPLOAD_BYTES + 1)
    response = client.post(
        URL, files={"file": ("big.gpx", data, "application/gpx+xml")}
    )
    assert_error(response, 413, "file_too_large")
    assert spy.calls == 0
    assert spy.closed_at_413 == [True]


def test_the_upload_is_closed_when_the_parse_then_fails(
    spy: Spy, client: TestClient
) -> None:
    response = client.post(
        URL, files={"file": ("bad.gpx", b"not xml", "application/gpx+xml")}
    )
    assert_error(response, 422, "invalid_gpx")
    assert spy.closed_at_parse == [True]


@pytest.fixture
async def make_client() -> AsyncIterator[Callable[[FastAPI], httpx.AsyncClient]]:
    clients: list[httpx.AsyncClient] = []

    def make(app: FastAPI) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


@pytest.mark.anyio
async def test_a_request_waiting_for_the_parse_slot_has_already_closed_its_upload(
    settings: Settings,
    spy: Spy,
    make_client: Callable[[FastAPI], httpx.AsyncClient],
) -> None:
    app = create_app(settings)
    client = make_client(app)
    limiter: anyio.CapacityLimiter = app.state.parse_limiter
    statuses: list[int] = []

    async def post(filename: str) -> None:
        response = await client.post(
            URL, files={"file": (filename, VALID, "application/gpx+xml")}
        )
        statuses.append(response.status_code)

    try:
        async with anyio.create_task_group() as group:
            group.start_soon(post, "hold.gpx")
            with anyio.fail_after(10):
                while spy.calls < 1:
                    await anyio.sleep(0.01)
            group.start_soon(post, "waiter.gpx")
            with anyio.fail_after(10):
                while len(spy.uploads) < 2:
                    await anyio.sleep(0.01)
            with anyio.fail_after(10):  # the waiter is queued on the parse slot
                while limiter.statistics().tasks_waiting < 1:
                    await anyio.sleep(0.01)
            while_waiting = (spy.calls, list(statuses), spy.all_closed())
            spy.release.set()
    finally:
        spy.release.set()
    # the waiter had not reached the parser, nothing had answered, and both uploads
    # were already closed
    assert while_waiting == (1, [], True)
    assert statuses == [200, 200]
    assert spy.closed_at_parse == [True, True]
