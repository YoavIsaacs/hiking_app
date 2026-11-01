"""ElevationClient against httpx.MockTransport (ADR 0005 sections 4 and 5).

No respx and no app here: this is the client's own contract (batching, order, retry
budget, error mapping, wall-clock timeout). The endpoint tests prove the wiring.
"""

import asyncio
import re
import time
import tomllib
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import anyio
import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pytest_socket import SocketBlockedError, SocketConnectBlockedError

from app.clients.elevation import ElevationClient, LookupResult
from app.routes.params import ELEVATION_MAX_CALLS, LOOKUP_MAX_POINTS
from tests.elevation_support import (
    coord,
    query_pairs,
    restream,
    synthetic_elevation,
    synthetic_handler,
)

BASE = "http://open-meteo.test"
Coords = list[tuple[float, float]]
Mock = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


def coords(n: int) -> Coords:
    return [(31.0 + i * 0.00123, 34.0 - i * 0.00071) for i in range(n)]


def expected_values(cs: Coords) -> tuple[float, ...]:
    return tuple(synthetic_elevation(coord(a), coord(b)) for a, b in cs)


async def run(
    handler: Mock, cs: Coords, *, timeout_s: float = 5.0
) -> tuple[LookupResult, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    async def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result = handler(request)
        return restream(result if isinstance(result, httpx.Response) else await result)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(recording), base_url=BASE
    ) as http:
        result = await ElevationClient(http, timeout_s=timeout_s).lookup(cs)
    return result, seen


def flatten(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in flatten(inner)]
    return [exc]


def is_socket_block(exc: BaseException) -> bool:
    """pytest-socket's error, in either of the two shapes it takes in this repo.

    The error classes call ``warnings.warn`` in ``__init__``, and pyproject sets
    ``filterwarnings = error``, so the warning is raised in place of the RuntimeError
    subclass. Both mean "an accidental live call was stopped".
    """
    if isinstance(exc, SocketBlockedError | SocketConnectBlockedError):
        return True
    return isinstance(exc, UserWarning) and "A test tried to use socket" in str(exc)


def ok_body(n: int) -> bytes:
    return b'{"elevation": [' + b",".join(b"10" for _ in range(n)) + b"]}"


pytestmark = pytest.mark.anyio


# --- success -----------------------------------------------------------------------


async def test_one_point_is_one_call_and_comes_back_as_a_tuple() -> None:
    cs = coords(1)
    result, seen = await run(synthetic_handler, cs)
    assert result == LookupResult(
        elevations=expected_values(cs),
        outcome="ok",
        calls=1,
        batches=1,
        status_code=None,
    )
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("n", "batches"), [(2, 1), (100, 1), (101, 2), (250, 3), (400, 4)]
)
async def test_n_points_cost_ceil_n_over_100_calls(n: int, batches: int) -> None:
    cs = coords(n)
    result, seen = await run(synthetic_handler, cs)
    assert result.outcome == "ok"
    assert (result.calls, result.batches, len(seen)) == (batches, batches, batches)
    assert result.elevations == expected_values(cs)


async def test_values_stay_in_input_order_when_batches_finish_out_of_order() -> None:
    cs = coords(250)

    async def slow_first_batch(request: httpx.Request) -> httpx.Response:
        pairs = query_pairs(request)
        if pairs[0][0] == coord(cs[0][0]):
            await anyio.sleep(0.1)  # the first batch answers last
        return synthetic_handler(request)

    result, _ = await run(slow_first_batch, cs)
    assert result.elevations == expected_values(cs)


async def test_requests_are_plain_gets_with_two_params_at_five_decimals() -> None:
    cs = coords(150)
    _, seen = await run(synthetic_handler, cs)
    for request in seen:
        pairs = query_pairs(request)  # method, path, exact param names, equal lengths
        assert len(pairs) <= 100
        for lat, lon in pairs:
            assert re.fullmatch(r"-?\d+\.\d{5}", lat) and re.fullmatch(
                r"-?\d+\.\d{5}", lon
            )
    sent = [p for r in seen for p in query_pairs(r)]
    assert sorted(sent) == sorted((coord(a), coord(b)) for a, b in cs)


@pytest.mark.parametrize("n", [0, LOOKUP_MAX_POINTS + 1, 1000])
async def test_zero_or_too_many_coordinates_is_a_programming_error(n: int) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(synthetic_handler), base_url=BASE
    ) as http:
        with pytest.raises(ValueError, match=r".+"):
            await ElevationClient(http, timeout_s=1.0).lookup(coords(n))


async def test_exactly_the_maximum_number_of_coordinates_is_accepted() -> None:
    result, _ = await run(synthetic_handler, coords(LOOKUP_MAX_POINTS))
    assert result.outcome == "ok" and result.calls == 4


# --- timeouts: a true wall-clock bound ---------------------------------------------


async def test_a_handler_that_outsleeps_timeout_s_gives_outcome_timeout() -> None:
    async def sleeper(request: httpx.Request) -> httpx.Response:
        await anyio.sleep(5)
        return synthetic_handler(request)

    started = time.monotonic()
    result, seen = await run(sleeper, coords(10), timeout_s=0.05)
    elapsed = time.monotonic() - started
    assert result.outcome == "timeout"
    assert result.elevations is None and result.status_code is None
    assert (result.calls, result.batches) == (2, 1)  # one retry, then give up
    assert len(seen) == 2
    assert elapsed < 2.0, "2 attempts of 0.05 s must not take seconds"


async def test_a_slow_body_read_counts_against_the_same_deadline() -> None:
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b'{"elevation": ['
            await anyio.sleep(5)
            yield b"10]}"

    def slow(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SlowBody())

    started = time.monotonic()
    result, _ = await run(slow, coords(1), timeout_s=0.05)
    assert result.outcome == "timeout"
    assert time.monotonic() - started < 2.0


@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout]
)
async def test_httpx_timeouts_are_outcome_timeout_and_retried_once(
    exc: type[httpx.TimeoutException],
) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise exc("t")

    result, seen = await run(boom, coords(5))
    assert (result.outcome, result.elevations, result.calls) == ("timeout", None, 2)
    assert len(seen) == 2


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.WriteError],
)
async def test_transport_errors_are_outcome_transport_error_and_retried_once(
    exc: type[httpx.TransportError],
) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise exc("t")

    result, seen = await run(boom, coords(5))
    assert (result.outcome, result.elevations, result.calls) == (
        "transport_error",
        None,
        2,
    )
    assert len(seen) == 2


async def test_a_transport_error_then_success_is_a_success_with_one_retry() -> None:
    attempts = 0

    def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("blip")
        return synthetic_handler(request)

    result, _ = await run(flaky, coords(5))
    assert result.outcome == "ok" and result.calls == 2 and result.batches == 1


# --- HTTP status ---------------------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_5xx_is_retried_once_then_reported_with_its_status(status: int) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="upstream")

    result, seen = await run(fail, coords(5))
    assert (result.outcome, result.status_code, result.calls) == (
        "http_status",
        status,
        2,
    )
    assert result.elevations is None and len(seen) == 2


async def test_503_then_200_is_a_success_and_calls_is_batches_plus_one() -> None:
    cs = coords(250)
    failed = False

    def one_blip(request: httpx.Request) -> httpx.Response:
        nonlocal failed
        if not failed and query_pairs(request)[0][0] == coord(cs[100][0]):
            failed = True
            return httpx.Response(503)
        return synthetic_handler(request)

    result, seen = await run(one_blip, cs)
    assert result.outcome == "ok" and result.elevations == expected_values(cs)
    assert (result.batches, result.calls, len(seen)) == (3, 4, 4)


async def test_503_twice_on_one_batch_gives_up_after_exactly_two_calls_for_it() -> None:
    cs = coords(250)
    second = coord(cs[100][0])

    def second_batch_is_down(request: httpx.Request) -> httpx.Response:
        if query_pairs(request)[0][0] == second:
            return httpx.Response(503)
        return synthetic_handler(request)

    result, seen = await run(second_batch_is_down, cs)
    assert (result.outcome, result.status_code, result.elevations) == (
        "http_status",
        503,
        None,
    )
    assert sum(1 for r in seen if query_pairs(r)[0][0] == second) == 2
    assert result.calls <= ELEVATION_MAX_CALLS and result.calls == len(seen)


async def test_the_retry_is_one_per_route_not_one_per_batch() -> None:
    attempted: set[str] = set()

    def every_batch_fails_once(request: httpx.Request) -> httpx.Response:
        first = query_pairs(request)[0][0]
        if first not in attempted:
            attempted.add(first)
            return httpx.Response(503)
        return synthetic_handler(request)

    result, seen = await run(every_batch_fails_once, coords(250))
    assert result.outcome == "http_status" and result.elevations is None
    assert result.calls == len(seen) <= ELEVATION_MAX_CALLS


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 301, 302, 307])
async def test_other_statuses_are_not_retried(status: int) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"location": BASE + "/elsewhere"})

    result, seen = await run(fail, coords(5))
    assert (result.outcome, result.status_code, result.calls) == (
        "http_status",
        status,
        1,
    )
    assert result.elevations is None and len(seen) == 1


async def test_a_429_on_one_of_three_batches_never_calls_any_batch_twice() -> None:
    cs = coords(250)
    third = coord(cs[200][0])

    def limited(request: httpx.Request) -> httpx.Response:
        if query_pairs(request)[0][0] == third:
            return httpx.Response(429, json={"error": True, "reason": "Minutely limit"})
        return synthetic_handler(request)

    result, seen = await run(limited, cs)
    assert (result.outcome, result.status_code, result.elevations) == (
        "http_status",
        429,
        None,
    )
    firsts = [query_pairs(r)[0][0] for r in seen]
    assert len(firsts) == len(set(firsts)), "no batch may be sent twice after a 429"


async def test_a_201_with_a_valid_looking_body_is_still_a_failure() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, content=ok_body(5))

    result, _ = await run(fail, coords(5))
    assert result.outcome == "http_status" and result.status_code == 201


# --- bad bodies ----------------------------------------------------------------------

BAD = {
    "not json": b"<html>nope</html>",
    "empty object": b"{}",
    "too few values": ok_body(4),
    "too many values": ok_body(6),
    "null": b"null",
    "string value": b'{"elevation": ["12", 1, 1, 1, 1]}',
    "bool value": b'{"elevation": [true, 1, 1, 1, 1]}',
    "NaN": b'{"elevation": [NaN, 1, 1, 1, 1]}',
    "overflowing exponent": b'{"elevation": [1e999, 1, 1, 1, 1]}',
    "implausible": b'{"elevation": [20000, 1, 1, 1, 1]}',
    "over 64 KiB": b'{"elevation": [1, 1, 1, 1, 1], "pad": "'
    + b"x" * (64 * 1024)
    + b'"}',
}


@pytest.mark.parametrize("body", BAD.values(), ids=BAD.keys())
async def test_a_bad_200_body_is_bad_response_and_is_not_retried(body: bytes) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    result, seen = await run(respond, coords(5))
    assert (result.outcome, result.calls, result.batches) == ("bad_response", 1, 1)
    assert result.elevations is None and result.status_code is None
    assert len(seen) == 1


async def test_the_content_type_is_ignored() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=ok_body(5), headers={"content-type": "text/plain"}
        )

    result, _ = await run(respond, coords(5))
    assert result.outcome == "ok" and result.elevations == (10.0,) * 5


async def test_one_bad_batch_of_three_fails_the_whole_lookup() -> None:
    cs = coords(203)
    last = coord(cs[200][0])

    def last_batch_is_garbage(request: httpx.Request) -> httpx.Response:
        if query_pairs(request)[0][0] == last:
            return httpx.Response(200, content=b'{"elevation": []}')
        return synthetic_handler(request)

    result, _ = await run(last_batch_is_garbage, cs)
    assert (result.outcome, result.elevations, result.batches) == (
        "bad_response",
        None,
        3,
    )


# --- exceptions that are not ours to swallow ---------------------------------


async def test_an_unexpected_exception_propagates_instead_of_becoming_a_result() -> (
    None
):
    def bug(request: httpx.Request) -> httpx.Response:
        raise KeyError("a pair the test did not record")

    with pytest.raises(BaseException) as caught:  # noqa: B017  # may be an ExceptionGroup
        await run(bug, coords(5))
    assert any(isinstance(e, KeyError) for e in flatten(caught.value))


# --- pytest-socket: an accidental live call fails loudly ------------------------------


async def test_a_live_call_is_blocked_by_pytest_socket_not_made_a_result() -> None:
    async with httpx.AsyncClient(base_url="http://192.0.2.1") as http:
        client = ElevationClient(http, timeout_s=1.0)
        with pytest.raises(BaseException) as caught:  # noqa: B017  # may be an ExceptionGroup
            await client.lookup(coords(3))
    leaves = flatten(caught.value)
    assert any(is_socket_block(e) for e in leaves), leaves


def test_the_event_loop_is_one_pytest_socket_can_guard() -> None:
    """On Windows the default Proactor loop connects with overlapped I/O, which skips
    pytest-socket's guard on ``socket.connect``: a forgotten mock would reach the real
    network. tests/conftest.py selects the selector loop; this pins that."""
    loop = asyncio.new_event_loop()
    try:
        assert "Proactor" not in type(loop).__name__
    finally:
        loop.close()


def test_the_pytest_configuration_disables_sockets() -> None:
    config = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--disable-socket" in addopts.split()
    assert "--allow-hosts=127.0.0.1" in addopts.split()


def test_a_raw_outbound_connection_is_refused_in_this_process() -> None:
    import socket

    with pytest.raises(Exception) as caught:  # noqa: B017  # see is_socket_block
        socket.create_connection(("192.0.2.1", 80), timeout=1)
    assert is_socket_block(caught.value), caught.value


# --- any failure pattern keeps the call count within the budget ---------------

BEHAVIOURS = [
    "ok",
    "s500",
    "s503",
    "s429",
    "s404",
    "timeout",
    "connect",
    "garbage",
    "short",
]


def behave(kind: str, request: httpx.Request) -> httpx.Response:
    if kind == "ok":
        return synthetic_handler(request)
    if kind[0] == "s" and kind[1:].isdigit():
        return httpx.Response(int(kind[1:]))
    if kind == "timeout":
        raise httpx.ReadTimeout("t")
    if kind == "connect":
        raise httpx.ConnectError("c")
    if kind == "garbage":
        return httpx.Response(200, content=b"garbage")
    return httpx.Response(200, content=ok_body(1))


@settings(max_examples=150, derandomize=True, deadline=None)
@given(st.lists(st.sampled_from(BEHAVIOURS), max_size=12))
def test_any_failure_pattern_on_a_400_point_route_keeps_calls_within_5(
    pattern: list[str],
) -> None:
    cs = coords(LOOKUP_MAX_POINTS)
    counter = 0
    non_200: list[int] = []  # statuses served, in the order served

    def scripted(request: httpx.Request) -> httpx.Response:
        nonlocal counter
        kind = pattern[counter] if counter < len(pattern) else "ok"
        counter += 1
        if kind[0] == "s" and kind[1:].isdigit():
            non_200.append(int(kind[1:]))
        return behave(kind, request)

    result, seen = anyio.run(run, scripted, cs)
    assert len(seen) == counter <= result.calls <= ELEVATION_MAX_CALLS
    assert result.batches == 4
    if result.outcome == "ok":
        assert result.elevations == expected_values(cs)
        # ADR 0005 section 7: the last non-200 status served before success, else None
        assert result.status_code == (non_200[-1] if non_200 else None)
    else:
        assert result.elevations is None
