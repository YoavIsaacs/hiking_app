"""Content-Encoding handling: the 64 KiB cap applies to raw and to inflated bytes."""

import gzip
import tracemalloc
import zlib

import httpx
import pytest

from app.clients.elevation import MAX_RESPONSE_BYTES, ElevationClient, new_http_client
from app.config import Settings

pytestmark = pytest.mark.anyio

BOMB = b"\0" * (64 * 1024 * 1024)


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://example.test")


async def _lookup_encoded(encoding: str, content: bytes) -> tuple[str, int, int]:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-encoding": encoding},
            stream=httpx.ByteStream(content),
        )

    async with _client(httpx.MockTransport(handler)) as http:
        client = ElevationClient(http, timeout_s=5.0)
        tracemalloc.start()
        try:
            result = await client.lookup([(1.0, 2.0)])
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    return result.outcome, calls, peak


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
async def test_a_decompression_bomb_is_bad_response_with_bounded_memory(
    encoding: str,
) -> None:
    packed = gzip.compress(BOMB) if encoding == "gzip" else zlib.compress(BOMB)
    assert len(packed) < MAX_RESPONSE_BYTES  # small raw, huge inflated
    outcome, calls, peak = await _lookup_encoded(encoding, packed)
    assert (outcome, calls) == ("bad_response", 1)
    assert peak < 2 * 1024 * 1024


async def test_brotli_is_bad_response_without_retry() -> None:
    outcome, calls, _ = await _lookup_encoded("br", b"\x0b\x00\x80{}\x03")
    assert (outcome, calls) == ("bad_response", 1)


async def test_a_raw_body_over_the_cap_is_bad_response_without_retry() -> None:
    outcome, calls, _ = await _lookup_encoded(
        "identity", b" " * (MAX_RESPONSE_BYTES + 1)
    )
    assert (outcome, calls) == ("bad_response", 1)


async def test_a_truncated_deflate_stream_is_bad_response() -> None:
    outcome, calls, _ = await _lookup_encoded(
        "deflate", zlib.compress(b'{"elevation": [1]}')[:-4]
    )
    assert (outcome, calls) == ("bad_response", 1)


async def test_the_request_asks_for_identity_encoding(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b'{"elevation": [5.0]}'))

    http = new_http_client(settings)
    http._transport = httpx.MockTransport(handler)  # noqa: SLF001
    async with http:
        result = await ElevationClient(http, timeout_s=5.0).lookup([(1.0, 2.0)])
    assert result.outcome == "ok"
    assert seen[0].headers["accept-encoding"] == "identity"


async def test_a_streamed_identity_body_over_the_cap_is_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, stream=httpx.ByteStream(b" " * (MAX_RESPONSE_BYTES + 1))
        )

    async with _client(httpx.MockTransport(handler)) as http:
        result = await ElevationClient(http, timeout_s=5.0).lookup([(1.0, 2.0)])
    assert result.outcome == "bad_response"


async def test_status_code_after_a_retried_5xx_is_the_last_non_200() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, stream=httpx.ByteStream(b'{"elevation": [5.0]}'))

    async with _client(httpx.MockTransport(handler)) as http:
        result = await ElevationClient(http, timeout_s=5.0).lookup([(1.0, 2.0)])
    assert (result.outcome, result.calls, result.status_code) == ("ok", 2, 503)
