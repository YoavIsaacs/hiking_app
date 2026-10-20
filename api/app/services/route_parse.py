"""Upload orchestration: parse, optional elevation lookup, summarise (ADR 0005 1)."""

import logging

import anyio

from app.clients.elevation import ElevationLookup
from app.models.route import RouteSummary
from app.routes.params import DEFAULT_PARAMS, ParseParams

logger = logging.getLogger("app.elevation")


async def summarise_upload(
    data: bytes,
    filename: str | None,
    *,
    limiter: anyio.CapacityLimiter,
    elevation: ElevationLookup | None,
    params: ParseParams = DEFAULT_PARAMS,
) -> RouteSummary:
    """Raise RouteParseError, or RuntimeError when no lifespan ran. Stub."""
    raise NotImplementedError
