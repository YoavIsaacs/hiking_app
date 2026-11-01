"""DEFECT (found in 1.3 verify): an undecodable Open-Meteo body was a 500.

A response that says ``Content-Encoding: gzip`` and is not gzip must be flagged
(200, ``elevation_unavailable``, no retry), like any malformed body.

This goes through the real app wiring (lifespan, settings, router) on an
``httpx.MockTransport``, not respx: respx decodes the body inside the transport and
would raise ``httpx.DecodingError`` before the client reads anything, which a real
transport never does. Here the client reads raw bytes and fails in its own decoder.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager

import httpx
from fastapi.testclient import TestClient

from tests.elevation.test_endpoint_lookup import assert_flagged, no_ele_route, post


def test_a_body_that_cannot_be_decoded_is_flagged_not_a_500(
    transport_client: Callable[
        [httpx.MockTransport], AbstractContextManager[TestClient]
    ],
) -> None:
    calls = 0

    def not_really_gzip(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=httpx.ByteStream(b"not gzip"),
        )

    with transport_client(httpx.MockTransport(not_really_gzip)) as client:
        assert_flagged(post(client, no_ele_route(60)[0]))
    assert calls == 1  # deterministic, like any bad body: no retry
