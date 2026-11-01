"""Upload orchestration: parse, optional elevation lookup, summarise (ADR 0005 1)."""

import logging
import time

import anyio

from app.clients.elevation import ElevationLookup
from app.models.route import RouteSummary
from app.models.warnings import ELEVATION_UNAVAILABLE
from app.routes.params import DEFAULT_PARAMS, ParseParams
from app.routes.summary import summarise_gpx, with_looked_up_elevation, with_warning

logger = logging.getLogger("app.elevation")


async def summarise_upload(
    data: bytes,
    filename: str | None,
    *,
    limiter: anyio.CapacityLimiter,
    elevation: ElevationLookup | None,
    params: ParseParams = DEFAULT_PARAMS,
) -> RouteSummary:
    """Raise RouteParseError, or RuntimeError when no lifespan ran."""
    summary = await anyio.to_thread.run_sync(
        summarise_gpx, data, filename, params, limiter=limiter
    )
    if summary.elevation_source != "none":
        return summary
    if elevation is None:
        raise RuntimeError("elevation lookup is not running (app lifespan not started)")

    started = time.perf_counter()
    result = await elevation.lookup([(p.lat, p.lon) for p in summary.points])
    logger.log(
        logging.INFO if result.outcome == "ok" else logging.WARNING,
        "elevation_lookup",
        extra={
            "points": len(summary.points),
            "batches": result.batches,
            "calls": result.calls,
            "outcome": result.outcome,
            "status_code": result.status_code,
            "duration_ms": (time.perf_counter() - started) * 1000,
        },
    )
    if result.elevations is None:
        return with_warning(summary, ELEVATION_UNAVAILABLE)
    # The default limiter: this must not queue behind a slow parse in the one slot.
    return await anyio.to_thread.run_sync(
        with_looked_up_elevation, summary, result.elevations, params
    )
