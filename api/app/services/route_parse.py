"""Upload orchestration: parse, optional elevation lookup, summarise (ADR 0005 1)."""

import logging
import time

import anyio

from app.clients.elevation import ElevationLookup
from app.models.route import RouteSummary
from app.models.warnings import ELEVATION_UNAVAILABLE
from app.routes.errors import RouteParseError
from app.routes.params import DEFAULT_PARAMS, ParseParams
from app.routes.summary import summarise_gpx, with_looked_up_elevation, with_warning

logger = logging.getLogger("app.elevation")


def _scrub(exc: BaseException) -> None:
    """Drop the tracebacks of an exception and its cause/context chain."""
    seen: set[int] = set()
    todo: list[BaseException | None] = [exc]
    while todo:
        item = todo.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        item.__traceback__ = None
        todo += [item.__cause__, item.__context__]


def summarise_in_worker(
    data: bytes, filename: str | None, params: ParseParams
) -> RouteSummary | RouteParseError:
    """Run in the worker thread; return a parse error instead of raising it.

    A raised error carries a traceback into the parser's frames (the upload, the
    parser), and anyio keeps the exception in a future that its own frame refers to,
    a reference cycle that holds the 10 MB upload until the cyclic collector runs.
    The error is scrubbed of tracebacks (they are never logged for a 422) and returned.
    """
    try:
        return summarise_gpx(data, filename, params)
    except RouteParseError as exc:
        _scrub(exc)
        return exc


async def summarise_upload(
    data: bytes,
    filename: str | None,
    *,
    limiter: anyio.CapacityLimiter,
    elevation: ElevationLookup | None,
    params: ParseParams = DEFAULT_PARAMS,
) -> RouteSummary:
    """Raise RouteParseError, or RuntimeError when no lifespan ran."""
    outcome = await anyio.to_thread.run_sync(
        summarise_in_worker, data, filename, params, limiter=limiter
    )
    if isinstance(outcome, RouteParseError):
        error = outcome
        del outcome  # the frame must not hold the error its traceback points back to
        try:
            raise error
        finally:
            del error
    summary = outcome
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
