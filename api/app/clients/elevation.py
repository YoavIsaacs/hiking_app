"""Open-Meteo elevation adapter (ADR 0005 4, 5). Contract stub: no behaviour yet."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

import httpx

from app.config import Settings
from app.routes.params import ELEVATION_BATCH_SIZE

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
    raise NotImplementedError


def split_batches(
    coords: Sequence[tuple[float, float]], size: int = ELEVATION_BATCH_SIZE
) -> list[Sequence[tuple[float, float]]]:
    raise NotImplementedError


def batch_query(batch: Sequence[tuple[float, float]]) -> dict[str, str]:
    raise NotImplementedError


def parse_elevations(body: bytes, expected: int) -> tuple[float, ...] | None:
    raise NotImplementedError


class ElevationClient:
    """Satisfies ElevationLookup."""

    def __init__(self, http: httpx.AsyncClient, *, timeout_s: float) -> None:
        raise NotImplementedError

    async def lookup(self, coords: Sequence[tuple[float, float]]) -> LookupResult:
        raise NotImplementedError


def new_http_client(settings: Settings) -> httpx.AsyncClient:
    raise NotImplementedError
