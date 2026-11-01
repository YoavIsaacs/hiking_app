"""DEFECT (found in 1.3 verify): an undecodable Open-Meteo body is a 500, not a warning.

``httpx.DecodingError`` (a response that says ``Content-Encoding: gzip`` and is not
gzip) derives from ``httpx.RequestError``, not ``httpx.TransportError``, so
``ElevationClient._attempt`` does not catch it and it escapes ``lookup`` as an
ExceptionGroup. The brief requires "Open-Meteo 5xx / malformed body / wrong count ->
flagged, no 500", and ADR 0005 section 4 lists the errors the client turns into a
result; this one is a malformed body. Expected: 200, the route flagged
``elevation_unavailable``, outcome ``bad_response``, no retry (calls == 1).

Fixed in the app: the client now reads raw bytes (the body is a stream here, as with
a real server) and decodes gzip itself, so a garbage gzip body is ``bad_response``.
"""

import httpx
from fastapi.testclient import TestClient

from tests.elevation.test_endpoint_lookup import assert_flagged, no_ele_route, post
from tests.elevation_support import ElevationApi


def test_a_body_that_cannot_be_decoded_is_flagged_not_a_500(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    def not_really_gzip(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=httpx.ByteStream(b"this is not gzip data at all"),
        )

    elevation_api.serve(not_really_gzip)
    assert_flagged(post(lifespan_client, no_ele_route(60)[0]))
    assert elevation_api.call_count == 1  # deterministic, like any bad body: no retry
