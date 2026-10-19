"""At most 2 parses run at once per app instance (ADR 0004 section 3.10).

Real wiring: ``create_app`` -> ``UploadLimitRoute`` router -> ``parse_route`` ->
``anyio.to_thread.run_sync(..., limiter=app.state.parse_limiter)``. Only the pure
pipeline is replaced, by a stub that blocks in its worker thread.
"""

import threading
from collections.abc import AsyncIterator, Callable

import anyio
import httpx
import pytest
from fastapi import FastAPI

import app.routers.routes as routes_module
from app.config import Settings
from app.main import create_app
from app.models.route import RouteSummary
from app.routes.params import MAX_CONCURRENT_PARSES, ParseParams
from app.routes.summary import summarise_gpx
from tests.routes.gpx_builders import gpx_bytes, out_and_back
from tests.routes.http_helpers import URL

VALID = gpx_bytes([out_and_back()])
HOLD = "hold.gpx"  # the stub blocks on this filename only
FREE = "free.gpx"


class Gate:
    """A stand-in for ``summarise_gpx`` that records concurrency and can block."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.release = threading.Event()
        self.in_flight = 0
        self.peak = 0
        self.calls = 0

    def __call__(
        self, data: bytes, filename: str | None, params: ParseParams | None = None
    ) -> RouteSummary:
        with self.lock:
            self.calls += 1
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        try:
            if filename == HOLD and not self.release.wait(timeout=15):
                raise RuntimeError("the test never released the parse")
            return summarise_gpx(data, filename)
        finally:
            with self.lock:
                self.in_flight -= 1

    def snapshot(self) -> tuple[int, int, int]:
        with self.lock:
            return self.in_flight, self.peak, self.calls


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Gate:
    gate = Gate()
    monkeypatch.setattr(routes_module, "summarise_gpx", gate)
    return gate


@pytest.fixture
async def app_client() -> AsyncIterator[Callable[[FastAPI], httpx.AsyncClient]]:
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


async def post(client: httpx.AsyncClient, filename: str, results: list[int]) -> None:
    response = await client.post(
        URL, files={"file": (filename, VALID, "application/gpx+xml")}
    )
    results.append(response.status_code)


async def wait_until(predicate: Callable[[], bool], what: str) -> None:
    with anyio.fail_after(10):
        while not predicate():
            await anyio.sleep(0.01)
    assert predicate(), what


def test_the_limit_is_two() -> None:
    assert MAX_CONCURRENT_PARSES == 2


@pytest.mark.anyio
async def test_only_two_of_four_simultaneous_parses_run_and_all_finish_200(
    settings: Settings,
    gate: Gate,
    app_client: Callable[[FastAPI], httpx.AsyncClient],
) -> None:
    client = app_client(create_app(settings))
    statuses: list[int] = []
    try:
        async with anyio.create_task_group() as group:
            for _ in range(4):
                group.start_soon(post, client, HOLD, statuses)
            await wait_until(lambda: gate.snapshot()[0] == 2, "two parses in flight")
            await anyio.sleep(0.3)  # time for a third to (wrongly) start
            in_flight, peak, calls = gate.snapshot()
            assert (in_flight, peak, calls) == (2, 2, 2)
            assert statuses == []  # nothing has answered yet: the others wait
            gate.release.set()
    finally:
        gate.release.set()
    assert statuses == [200, 200, 200, 200]
    in_flight, peak, calls = gate.snapshot()
    assert (in_flight, peak, calls) == (0, 2, 4)


@pytest.mark.anyio
async def test_a_waiting_request_is_served_as_soon_as_a_slot_frees(
    settings: Settings,
    gate: Gate,
    app_client: Callable[[FastAPI], httpx.AsyncClient],
) -> None:
    client = app_client(create_app(settings))
    statuses: list[int] = []
    try:
        async with anyio.create_task_group() as group:
            for _ in range(2):
                group.start_soon(post, client, HOLD, statuses)
            await wait_until(lambda: gate.snapshot()[0] == 2, "both slots held")
            group.start_soon(post, client, FREE, statuses)
            await anyio.sleep(0.3)
            assert gate.snapshot()[2] == 2  # the third has not reached the parser
            gate.release.set()
    finally:
        gate.release.set()
    assert statuses == [200, 200, 200]
    assert gate.snapshot()[1] == 2


@pytest.mark.anyio
async def test_a_slot_is_freed_when_a_parse_fails(
    settings: Settings,
    app_client: Callable[[FastAPI], httpx.AsyncClient],
) -> None:
    """422 answers must not leak limiter tokens: 6 failures in a row, then a success."""
    client = app_client(create_app(settings))
    statuses: list[int] = []
    for _ in range(6):
        response = await client.post(
            URL, files={"file": ("bad.gpx", b"not xml", "application/gpx+xml")}
        )
        statuses.append(response.status_code)
    await post(client, FREE, statuses)
    assert statuses == [422] * 6 + [200]


@pytest.mark.anyio
async def test_a_fresh_app_has_its_own_limiter_with_two_tokens(
    settings: Settings,
) -> None:
    first, second = create_app(settings), create_app(settings)
    assert first.state.parse_limiter is not second.state.parse_limiter
    assert first.state.parse_limiter.total_tokens == MAX_CONCURRENT_PARSES
    assert second.state.parse_limiter.total_tokens == MAX_CONCURRENT_PARSES


@pytest.mark.anyio
async def test_saturating_one_app_does_not_block_another_app(
    settings: Settings,
    gate: Gate,
    app_client: Callable[[FastAPI], httpx.AsyncClient],
) -> None:
    busy = app_client(create_app(settings))
    other = app_client(create_app(settings))
    held: list[int] = []
    free: list[int] = []
    try:
        async with anyio.create_task_group() as group:
            for _ in range(2):
                group.start_soon(post, busy, HOLD, held)
            await wait_until(lambda: gate.snapshot()[0] == 2, "busy app saturated")
            with anyio.fail_after(5):
                await post(other, FREE, free)  # would hang on a shared limiter
            assert free == [200]
            gate.release.set()
    finally:
        gate.release.set()
    assert held == [200, 200]
