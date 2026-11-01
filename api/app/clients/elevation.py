"""Open-Meteo elevation adapter (ADR 0005 4, 5)."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

import anyio
import httpx

from app.config import Settings
from app.routes.params import (
    ELEVATION_BATCH_SIZE,
    ELEVATION_MAX_RETRIES,
    LOOKUP_MAX_POINTS,
    MAX_PLAUSIBLE_ELEV_M,
    MIN_PLAUSIBLE_ELEV_M,
)

ELEVATION_PATH: Final = "/v1/elevation"
COORD_DECIMALS: Final = 5
MAX_RESPONSE_BYTES: Final = 64 * 1024
LookupOutcome = Literal[
    "ok", "timeout", "transport_error", "http_status", "bad_response"
]


@dataclass(frozen=True, slots=True)
class LookupResult:
    elevations: tuple[float, ...] | None  # None iff outcome != "ok"
    outcome: LookupOutcome
    calls: int  # attempts started, <= ELEVATION_MAX_CALLS
    batches: int
    status_code: int | None  # last non-200 status seen, for the log


class ElevationLookup(Protocol):
    async def lookup(self, coords: Sequence[tuple[float, float]]) -> LookupResult: ...


def format_coord(value: float) -> str:
    return f"{value:.{COORD_DECIMALS}f}"


def split_batches(
    coords: Sequence[tuple[float, float]], size: int = ELEVATION_BATCH_SIZE
) -> list[Sequence[tuple[float, float]]]:
    return [coords[i : i + size] for i in range(0, len(coords), size)]


def batch_query(batch: Sequence[tuple[float, float]]) -> dict[str, str]:
    return {
        "latitude": ",".join(format_coord(lat) for lat, _ in batch),
        "longitude": ",".join(format_coord(lon) for _, lon in batch),
    }


def _reject_constant(token: str) -> float:
    raise ValueError(f"non-finite JSON constant {token}")


def parse_elevations(body: bytes, expected: int) -> tuple[float, ...] | None:
    """The values of a valid response, else None (ADR 0005 4)."""
    try:
        data: object = json.loads(body, parse_constant=_reject_constant)
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        return None
    if not isinstance(data, dict):
        return None
    values: object = data.get("elevation")
    if not isinstance(values, list) or len(values) != expected:
        return None
    out: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        try:
            number = float(value)
        except OverflowError:  # an int too large for a float
            return None
        if not (MIN_PLAUSIBLE_ELEV_M <= number <= MAX_PLAUSIBLE_ELEV_M):
            return None  # also rejects inf; NaN fails every comparison
        out.append(number)
    return tuple(out)


@dataclass(slots=True)
class _Failure:
    outcome: LookupOutcome
    status_code: int | None = None


@dataclass(slots=True)
class _Lookup:
    """Mutable state of one lookup, shared by its concurrent batches."""

    retries_left: int = ELEVATION_MAX_RETRIES
    calls: int = 0
    failure: _Failure | None = None
    last_status: int | None = None


class ElevationClient:
    """Satisfies ElevationLookup."""

    def __init__(self, http: httpx.AsyncClient, *, timeout_s: float) -> None:
        self._http = http
        self._timeout_s = timeout_s

    async def lookup(self, coords: Sequence[tuple[float, float]]) -> LookupResult:
        if not 1 <= len(coords) <= LOOKUP_MAX_POINTS:
            raise ValueError(
                f"expected 1..{LOOKUP_MAX_POINTS} coordinates, got {len(coords)}"
            )
        batches = split_batches(coords)
        state = _Lookup()
        results: list[tuple[float, ...] | None] = [None] * len(batches)

        async with anyio.create_task_group() as group:

            async def run(index: int) -> None:
                values = await self._batch(batches[index], state)
                if values is None:
                    group.cancel_scope.cancel()
                else:
                    results[index] = values

            for index in range(len(batches)):
                group.start_soon(run, index)

        if state.failure is not None:
            return LookupResult(
                elevations=None,
                outcome=state.failure.outcome,
                calls=state.calls,
                batches=len(batches),
                status_code=state.last_status,
            )
        return LookupResult(
            elevations=tuple(v for r in results for v in r or ()),
            outcome="ok",
            calls=state.calls,
            batches=len(batches),
            status_code=None,
        )

    async def _batch(
        self, batch: Sequence[tuple[float, float]], state: _Lookup
    ) -> tuple[float, ...] | None:
        """One batch with its share of the route's retry; None on failure."""
        while True:
            state.calls += 1
            values, failure, retryable = await self._attempt(batch)
            if failure is None:
                return values
            if failure.status_code is not None:
                state.last_status = failure.status_code
            if retryable and state.retries_left > 0 and state.failure is None:
                state.retries_left -= 1
                continue
            if state.failure is None:
                state.failure = failure
            return None

    async def _attempt(
        self, batch: Sequence[tuple[float, float]]
    ) -> tuple[tuple[float, ...] | None, _Failure | None, bool]:
        """(values, failure, retryable): one HTTP call under a wall-clock deadline."""
        try:
            with anyio.fail_after(self._timeout_s):
                async with self._http.stream(
                    "GET", ELEVATION_PATH, params=batch_query(batch)
                ) as response:
                    status = response.status_code
                    if status != 200:
                        return None, _Failure("http_status", status), status >= 500
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            return None, _Failure("bad_response"), False
        except (TimeoutError, httpx.TimeoutException):
            return None, _Failure("timeout"), True
        except httpx.DecodingError:  # a RequestError, not a TransportError
            return None, _Failure("bad_response"), False
        except httpx.TransportError:
            return None, _Failure("transport_error"), True
        values = parse_elevations(bytes(body), len(batch))
        if values is None:
            return None, _Failure("bad_response"), False
        return values, None, False


def new_http_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.open_meteo_base_url,
        timeout=httpx.Timeout(settings.elevation_timeout_s),
        follow_redirects=False,
        headers={"User-Agent": f"hike-prep-api/{settings.version}"},
    )
