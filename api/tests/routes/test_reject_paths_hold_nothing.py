"""Every non-200 path of POST /v1/routes/parse, and the elevation-failure path, must not
keep the upload alive until the cyclic collector runs (ADR 0004 item 55/56).

``tests/unit/test_parse_no_cycles.py`` covers three ``invalid_gpx`` inputs. This file
covers the other shapes (``tests/routes/reject_shapes.py``) through the real app
(``create_app`` with its lifespan), with two measurements:

* **cycles**: the collector is off and ``DEBUG_SAVEALL`` is on; after the requests the
  collected garbage must hold no upload: no frame with a big ``bytes`` local, no open
  UploadFile, parser or reader;
* **retention**: the collector is off and ``tracemalloc`` is on; after the requests the
  traced memory must not have grown by anything near the size of the uploads.

Each case also pins the response it is meant to produce, so a shape that stops being
rejected the way it should is a failure here, not a silent pass.

These run in the TestClient, whose own plumbing can hold a request body. The
authoritative measurement of a leak is over HTTP in the image:
``python -m tests.routes.rss_probe --shape all``.
"""

import gc
import tracemalloc
import types
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.elevation_support import (
    ElevationApi,
    body_handler,
    raising_handler,
    read_timeout,
    status_handler,
)
from tests.routes.http_helpers import URL
from tests.routes.reject_shapes import (
    MIB,
    Shape,
    accepted,
    rejects,
    too_large,
    validation,
)

REPEATS = 3


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


@pytest.fixture
def traced() -> Iterator[None]:
    gc.collect()
    gc.disable()
    tracemalloc.start()
    try:
        yield
    finally:
        tracemalloc.stop()
        gc.enable()
        gc.collect()


def watched_garbage() -> list[str]:
    """What the unreachable garbage holds of the request: a frame with a local that is a
    big bytes object (the upload), an open UploadFile, a parser or a reader.

    Library frames that cycle through a handled exception (FastAPI's validation error)
    are not counted: they hold nothing of the upload."""
    gc.garbage.clear()
    gc.collect()
    found: list[str] = []
    for o in gc.garbage:
        name = type(o).__name__
        if name == "UploadFile" and not o.file.closed:
            found.append("open UploadFile")
        elif name in ("xmlparser", "_GpxReader"):
            found.append(name)
        elif isinstance(o, types.FrameType):
            found.extend(
                f"frame {o.f_code.co_name} holds {k} ({len(v) / MIB:.1f} MiB)"
                for k, v in o.f_locals.items()
                if isinstance(v, bytes | bytearray) and len(v) > MIB
            )
    gc.garbage.clear()
    return found


def send(client: TestClient, shape: Shape) -> httpx.Response:
    headers = {"Content-Type": shape.headers_content_type}
    response: httpx.Response = client.post(URL, content=shape.body, headers=headers)
    return response


def send_ok(client: TestClient, shape: Shape) -> None:
    response = send(client, shape)
    assert response.status_code == shape.status, response.text[:200]
    if shape.code is not None:
        assert response.json()["code"] == shape.code, response.text[:200]


def held_by(client: TestClient, shape: Shape) -> float:
    send_ok(client, shape)  # warm up lazily created state
    before, _ = tracemalloc.get_traced_memory()
    for _ in range(REPEATS):
        send_ok(client, shape)
    return float(tracemalloc.get_traced_memory()[0] - before)


REJECTS = rejects()
TOO_LARGE = {k: v for k, v in too_large().items() if not v.chunked}
VALIDATION = validation()
ALL_4XX = REJECTS | TOO_LARGE | VALIDATION


@pytest.mark.parametrize("name", ALL_4XX)
def test_rejected_upload_leaves_no_cyclic_garbage(
    lifespan_client: TestClient, collector_off: None, name: str
) -> None:
    shape = ALL_4XX[name]
    for _ in range(REPEATS):
        send_ok(lifespan_client, shape)
    assert watched_garbage() == []


@pytest.mark.parametrize("name", ALL_4XX)
def test_rejected_upload_is_not_retained_while_the_collector_is_off(
    lifespan_client: TestClient, traced: None, name: str
) -> None:
    held = held_by(lifespan_client, ALL_4XX[name])
    assert held < MIB, f"{name}: {held / MIB:.1f} MiB held after {REPEATS} uploads"


# --- accepted uploads whose elevation lookup fails (200 + elevation_unavailable) ---

FAILURES = {
    "http_500": status_handler(500),
    "http_429": status_handler(429),
    "read_timeout": raising_handler(read_timeout),
    "garbage_body": body_handler(b"garbage"),
}
NO_ELEVATION = accepted()["200_no_elevation_big"]


@pytest.mark.parametrize("name", FAILURES)
def test_elevation_failure_leaves_no_cyclic_garbage(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
    collector_off: None,
    name: str,
) -> None:
    elevation_api.serve(FAILURES[name])
    for _ in range(REPEATS):
        response = send(lifespan_client, NO_ELEVATION)
        assert response.status_code == 200, response.text[:200]
        assert [w["code"] for w in response.json()["warnings"]] == [
            "elevation_unavailable"
        ]
    assert watched_garbage() == []


@pytest.mark.parametrize("name", FAILURES)
def test_elevation_failure_does_not_retain_the_upload(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
    traced: None,
    name: str,
) -> None:
    elevation_api.serve(FAILURES[name])
    held = held_by(lifespan_client, NO_ELEVATION)
    assert held < MIB, f"{name}: {held / MIB:.1f} MiB held after {REPEATS} uploads"


def test_an_accepted_upload_leaves_no_cyclic_garbage(
    lifespan_client: TestClient, collector_off: None
) -> None:
    for _ in range(REPEATS):
        send_ok(lifespan_client, accepted()["200_valid_big"])
    assert watched_garbage() == []
