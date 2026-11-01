"""QA verify probes for step 1.3: failure paths the first tests did not reach.

Every test runs the real app with its lifespan (``lifespan_client``) against the respx
router, like ``test_endpoint_lookup.py``.
"""

import gzip
import logging
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.elevation.test_endpoint_lookup import (
    NO_ELE,
    assert_backfilled,
    assert_flagged,
    no_ele_route,
    post,
)
from tests.elevation_support import (
    ElevationApi,
    ok_body,
    query_pairs,
    synthetic_elevation,
    synthetic_handler,
)


def _gzip_response(content: bytes) -> httpx.Response:
    # a stream, so that decoding happens in the client's read, as with a real server
    return httpx.Response(
        200,
        headers={"content-encoding": "gzip"},
        stream=httpx.ByteStream(content),
    )


def test_a_truncated_gzip_body_is_flagged_not_a_500(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    truncated = gzip.compress(b'{"elevation": [1]}')[:-6]
    elevation_api.serve(lambda request: _gzip_response(truncated))
    assert_flagged(post(lifespan_client, no_ele_route(60)[0]))


def test_a_valid_gzip_body_is_a_success(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    def compressed(request: httpx.Request) -> httpx.Response:
        values = [synthetic_elevation(lat, lon) for lat, lon in query_pairs(request)]
        return _gzip_response(gzip.compress(ok_body(values)))

    elevation_api.serve(compressed)
    assert_backfilled(post(lifespan_client, no_ele_route(60)[0]))


def test_no_log_record_at_debug_level_carries_a_coordinate(
    settings: Settings,
    elevation_api: ElevationApi,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Route coordinates are user data and must not reach Cloud Logging, even with
    HIKE_LOG_LEVEL=DEBUG (httpx and httpcore log request URLs at INFO and DEBUG)."""
    debug = settings.model_copy(update={"log_level": "DEBUG"})
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(debug)) as client:
        assert_backfilled(post(client, NO_ELE.read_bytes(), NO_ELE.name))
    # the lookup really was logged, so an empty capture cannot pass the check below
    assert [r for r in caplog.records if r.getMessage() == "elevation_lookup"]
    sent = {c for r in elevation_api.requests for p in query_pairs(r) for c in p}
    assert len(sent) > 50
    text = "\n".join(f"{r.getMessage()} {r.args!r}" for r in caplog.records)
    assert not [c for c in sent if c in text]
    assert not re.search(r"latitude=", text)


def test_a_persistent_5xx_gives_up_after_one_retry_even_if_the_api_would_recover(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    """Fails cleanly (not by hanging) if the retry is unbounded: the API heals on its
    5th call, and a route that retried until then would come back as a success."""

    def heals_late(request: httpx.Request) -> httpx.Response:
        if elevation_api.call_count < 5:
            return httpx.Response(503)
        return synthetic_handler(request)

    elevation_api.serve(heals_late)
    assert_flagged(post(lifespan_client, no_ele_route(60)[0]))
    assert elevation_api.call_count == 2
