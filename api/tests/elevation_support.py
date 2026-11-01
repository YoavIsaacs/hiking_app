"""Shared helpers for the elevation-backfill tests (ADR 0005 section 7).

* ``ElevationApi``: a respx router on ``GET {base}/v1/elevation`` that counts every
  request and answers through a replaceable handler.
* ``recorded_handler``: replay by coordinate, not by URL, from the recordings in
  ``tests/fixtures/http/elevation/``. An unknown pair raises ``KeyError`` (the client
  does not catch it, so the test fails loudly).
* ``synthetic_handler``: a fixed deterministic function of lat/lon, for synthetic routes
  and fuzzing.
* Failure handlers (timeouts, status codes, bad bodies).

Formatting is done here with ``f"{v:.5f}"`` on purpose: the app's ``format_coord`` must
never be needed to build the oracle that tests it.
"""

import json
import math
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import respx

RECORDED_DIR = Path(__file__).parent / "fixtures" / "http" / "elevation"
TEL_HADID = "alltrails-tel-hadid-loop"
MODIIN = "alltrails-modiin-hills-south-double-loop"
BEN_SHEMEN = "alltrails-ben-shemen-hertzl-singletrack"
PARENTS = (TEL_HADID, MODIIN, BEN_SHEMEN)
ELEVATION_PATH = "/v1/elevation"
MAX_BATCH = 100

Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]
Pair = tuple[str, str]


def coord(value: float) -> str:
    """The wire format of one coordinate (ADR 0005 section 4)."""
    return f"{value:.5f}"


def pair_of(lat: float, lon: float) -> Pair:
    return coord(lat), coord(lon)


@dataclass(frozen=True)
class Recording:
    stem: str
    meta: dict[str, object]
    table: dict[Pair, float]  # (lat, lon) as sent -> recorded elevation
    raw_bodies: list[bytes]


def load_recording(stem: str) -> Recording:
    meta = json.loads((RECORDED_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    table: dict[Pair, float] = {}
    for point in meta["points"]:
        lat, lon = point["sent"].split(",")
        elevation = float(point["elevation_m"])
        # the same coordinate sent twice must have been answered the same way
        assert table.setdefault((lat, lon), elevation) == elevation
        # the stored GPX floats and the sent strings agree (5 dp)
        assert pair_of(point["lat"], point["lon"]) == (lat, lon)
    raws = [(RECORDED_DIR / r["raw"]).read_bytes() for r in meta["requests"]]
    return Recording(stem, meta, table, raws)


def recorded_table(*stems: str) -> dict[Pair, float]:
    table: dict[Pair, float] = {}
    for stem in stems:
        table.update(load_recording(stem).table)
    return table


def synthetic_elevation(lat: str, lon: str) -> float:
    """Any fixed deterministic function of lat/lon, always plausible (50..550 m)."""
    return float(
        round(
            300
            + 150 * math.sin(float(lat) * 997.0)
            + 100 * math.cos(float(lon) * 991.0)
        )
    )


def query_pairs(request: httpx.Request) -> list[Pair]:
    """The (lat, lon) strings of one request; asserts the query shape on the way."""
    params = request.url.params
    assert request.method == "GET"
    assert request.url.path == ELEVATION_PATH
    assert set(params.keys()) == {"latitude", "longitude"}, dict(params)
    lats = params["latitude"].split(",")
    lons = params["longitude"].split(",")
    assert len(lats) == len(lons), "latitude and longitude differ in length"
    assert 1 <= len(lats) <= MAX_BATCH, f"{len(lats)} coordinates in one request"
    assert " " not in params["latitude"] + params["longitude"]
    return list(zip(lats, lons, strict=True))


def streamed(
    status: int, body: bytes = b"", headers: dict[str, str] | None = None
) -> httpx.Response:
    """A response whose body is a stream, not pre-read.

    ``httpx.Response(content=...)`` is already in memory and already decoded, which
    is not what a real transport hands the client. A stream makes the client's
    ``aiter_raw()`` path run, and a ``Content-Encoding`` header is then the client's to
    decode (send the compressed bytes).
    """
    return httpx.Response(status, headers=headers, stream=httpx.ByteStream(body))


def restream(response: httpx.Response) -> httpx.Response:
    """The same response as a stream if it was built with ``content=``/``json=``."""
    if not response.is_stream_consumed:
        return response
    headers = {
        k: v for k, v in response.headers.items() if k.lower() != "content-length"
    }
    return streamed(response.status_code, response.content, headers)


def ok_body(values: Sequence[float]) -> bytes:
    return json.dumps({"elevation": list(values)}).encode()


def ok_response(values: Sequence[float]) -> httpx.Response:
    return streamed(200, ok_body(values), {"content-type": "application/json"})


def synthetic_handler(request: httpx.Request) -> httpx.Response:
    return ok_response(
        [synthetic_elevation(lat, lon) for lat, lon in query_pairs(request)]
    )


def recorded_handler(table: dict[Pair, float]) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        return ok_response(
            [table[pair] for pair in query_pairs(request)]
        )  # KeyError: loud

    return handle


def status_handler(
    status: int, body: bytes = b'{"error":true,"reason":"upstream detail"}'
) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        query_pairs(request)
        return streamed(status, body)

    return handle


def body_handler(body: bytes, status: int = 200) -> Handler:
    return status_handler(status, body)


def raising_handler(exc: Callable[[], Exception]) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        query_pairs(request)
        raise exc()

    return handle


def read_timeout() -> httpx.ReadTimeout:
    return httpx.ReadTimeout("recorded read timeout")


def connect_timeout() -> httpx.ConnectTimeout:
    return httpx.ConnectTimeout("recorded connect timeout")


class ElevationApi:
    """The fake Open-Meteo. ``requests`` holds every request the app made, in order."""

    def __init__(self, router: respx.MockRouter) -> None:
        self.router = router
        self.requests: list[httpx.Request] = []
        self.handler: Handler = synthetic_handler
        route = router.get(ELEVATION_PATH)
        route.side_effect = self._dispatch

    async def _dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        result = self.handler(request)
        if isinstance(result, httpx.Response):
            return restream(result)
        return restream(await result)

    # --- configuring ---
    def serve(self, handler: Handler) -> None:
        self.handler = handler

    def serve_recorded(self, *stems: str) -> None:
        self.handler = recorded_handler(recorded_table(*stems))

    def reset(self) -> None:
        self.requests.clear()
        self.handler = synthetic_handler

    # --- observing ---
    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def batch_sizes(self) -> list[int]:
        return [len(query_pairs(r)) for r in self.requests]

    def calls_for_batch_starting_at(self, first_pair: Pair) -> int:
        """How many requests started with this coordinate (a batch's first point)."""
        return sum(1 for r in self.requests if query_pairs(r)[0] == first_pair)


@contextmanager
def elevation_mock(base_url: str) -> Iterator[ElevationApi]:
    with respx.mock(base_url=base_url, assert_all_called=False) as router:
        yield ElevationApi(router)
