"""A rejected upload leaves no reference cycle behind (ADR 0004 item 55).

A cycle holds the upload and the parser until the cyclic collector runs, which under a
stream of hostile uploads let RSS ratchet up to the container limit. These tests turn
the collector off, run rejected uploads, then collect with DEBUG_SAVEALL and assert that
nothing the request held (frames, parser, reader, upload) was cyclic garbage.
"""

import gc
import types
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.routes.errors import InvalidGpx, TooManyPoints
from app.routes.params import DEFAULT_PARAMS
from app.services.route_parse import summarise_in_worker
from tests.routes.gpx_builders import gpx_bytes, out_and_back
from tests.routes.http_helpers import (
    URL,
    multipart_content_type,
    multipart_head,
    multipart_tail,
)

DTD = b'<!DOCTYPE gpx [<!ENTITY a "b">]><gpx version="1.1"/>'
NOT_XML = b"<gpx><trk>" + b"x" * 5000
NOT_GPX = b"<html></html>"
HOSTILE = [
    pytest.param(DTD, id="dtd"),
    pytest.param(NOT_XML, id="malformed"),
    pytest.param(NOT_GPX, id="not-gpx"),
]
WATCHED = {"frame", "traceback", "xmlparser", "_GpxReader", "UploadFile"}


@pytest.fixture
def collector_off() -> Iterator[None]:
    gc.collect()
    gc.disable()
    gc.set_debug(gc.DEBUG_SAVEALL)
    try:
        yield
    finally:
        gc.set_debug(0)
        gc.garbage.clear()
        gc.enable()


def watched_garbage() -> list[str]:
    gc.garbage.clear()
    gc.collect()
    found = [
        type(o).__name__
        for o in gc.garbage
        if type(o).__name__ in WATCHED or isinstance(o, types.FrameType)
    ]
    gc.garbage.clear()
    return found


@pytest.mark.parametrize("data", HOSTILE)
def test_worker_returns_scrubbed_error_without_cycles(
    collector_off: None, data: bytes
) -> None:
    outcome = summarise_in_worker(data, "x.gpx", DEFAULT_PARAMS)
    assert isinstance(outcome, InvalidGpx)
    chain = [outcome, outcome.__cause__, outcome.__context__]
    assert all(e is None or e.__traceback__ is None for e in chain)
    del outcome, chain
    assert watched_garbage() == []


def test_worker_returns_summary_unchanged() -> None:
    data = gpx_bytes([out_and_back()])
    assert not isinstance(
        summarise_in_worker(data, "x.gpx", DEFAULT_PARAMS), InvalidGpx | TooManyPoints
    )


@pytest.mark.parametrize("data", HOSTILE)
def test_rejected_upload_over_http_leaves_no_cyclic_garbage(
    lifespan_client: TestClient, collector_off: None, data: bytes
) -> None:
    body = multipart_head() + data + multipart_tail()
    headers = {"Content-Type": multipart_content_type()}
    for _ in range(3):
        response = lifespan_client.post(URL, content=body, headers=headers)
        assert response.status_code == 422
    assert watched_garbage() == []
