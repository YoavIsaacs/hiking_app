"""Errors raised while reading a response: which are results, which propagate."""

import httpx
import pytest

from app.clients.elevation import ElevationClient

pytestmark = pytest.mark.anyio


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://example.test")


async def test_undecodable_body_is_bad_response_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=b"not gzip"
        )

    async with _client(httpx.MockTransport(handler)) as http:
        result = await ElevationClient(http, timeout_s=1.0).lookup([(1.0, 2.0)])
    assert result.outcome == "bad_response"
    assert result.elevations is None
    assert calls == 1


async def test_remote_protocol_error_is_a_retried_transport_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.RemoteProtocolError("peer closed", request=request)

    async with _client(httpx.MockTransport(handler)) as http:
        result = await ElevationClient(http, timeout_s=1.0).lookup([(1.0, 2.0)])
    assert result.outcome == "transport_error"
    assert calls == 2


async def test_stream_misuse_errors_still_propagate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.StreamConsumed()

    async with _client(httpx.MockTransport(handler)) as http:
        with pytest.raises(BaseExceptionGroup) as info:
            await ElevationClient(http, timeout_s=1.0).lookup([(1.0, 2.0)])
    assert info.group_contains(httpx.StreamConsumed)
