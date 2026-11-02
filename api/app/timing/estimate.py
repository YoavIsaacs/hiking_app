"""Duration estimator (ADR 0006 §2-§6). Pure: no I/O, clock, randomness or settings."""

import math
from bisect import bisect_right
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.models.route import RouteSummary, TrackPoint
from app.models.timing import Timing
from app.timing.params import (
    MAX_ABS_SLOPE,
    MAX_PACE_FACTOR,
    MAX_REST_MIN_PER_HOUR,
    MIN_PACE_FACTOR,
    SLOPE_WINDOW_M,
)
from app.timing.tobler import speed_kmh


def _check_monotonic(dists: Sequence[float]) -> None:
    for prev, cur in zip(dists, dists[1:], strict=False):
        if cur < prev:
            raise ValueError("dist_m must not decrease")


def _elevation_at(x: float, dists: Sequence[float], elevs: Sequence[float]) -> float:
    """Piecewise-linear E(x); at a repeated distance the last point wins."""
    i = bisect_right(dists, x) - 1
    if i >= len(dists) - 1:
        return elevs[-1]
    span = dists[i + 1] - dists[i]  # > 0: dists[i + 1] > x >= dists[i]
    return elevs[i] + (elevs[i + 1] - elevs[i]) * (x - dists[i]) / span


def segment_slopes(points: Sequence[TrackPoint]) -> list[float]:
    """len(points) - 1 windowed, clamped slopes (ADR 0006 §2/§3).

    Raises ValueError if dist_m decreases.
    """
    dists = [p.dist_m for p in points]
    _check_monotonic(dists)
    n_segments = len(points) - 1
    elevs: list[float] = []
    for p in points:
        if p.elev_m is None:
            return [0.0] * n_segments
        elevs.append(p.elev_m)

    total = dists[-1]
    slopes: list[float] = []
    for i in range(n_segments):
        delta = dists[i + 1] - dists[i]
        if delta == 0:
            slopes.append(0.0)
            continue
        mid = (dists[i] + dists[i + 1]) / 2
        half = max(SLOPE_WINDOW_M, delta) / 2
        a = max(dists[0], mid - half)
        b = min(total, mid + half)
        s = (_elevation_at(b, dists, elevs) - _elevation_at(a, dists, elevs)) / (b - a)
        slopes.append(max(-MAX_ABS_SLOPE, min(MAX_ABS_SLOPE, s)))
    return slopes


def estimate(
    route: RouteSummary,
    start_time: datetime,
    pace_factor: float,
    rest_min_per_hour: float,
) -> Timing:
    """Time the route (ADR 0006 §4-§6).

    Raises ValueError on a naive start_time, out-of-range pace or rest, or
    decreasing dist_m.
    """
    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise ValueError("start_time must be timezone-aware")
    if not (
        math.isfinite(pace_factor) and MIN_PACE_FACTOR <= pace_factor <= MAX_PACE_FACTOR
    ):
        raise ValueError("pace_factor out of range")
    if not (
        math.isfinite(rest_min_per_hour)
        and 0 <= rest_min_per_hour <= MAX_REST_MIN_PER_HOUR
    ):
        raise ValueError("rest_min_per_hour out of range")

    points = route.points
    slopes = segment_slopes(points)

    cumulative = [0.0]  # C_j: pace-1 moving minutes to reach point j
    for i, s in enumerate(slopes):
        delta = points[i + 1].dist_m - points[i].dist_m
        cumulative.append(cumulative[-1] + 0.06 * delta / speed_kmh(s))

    base = cumulative[-1]
    k = pace_factor * (1 + rest_min_per_hour / 60)
    start_utc = start_time.astimezone(UTC)
    etas = [start_time] + [
        (start_utc + timedelta(minutes=c * k)).astimezone(start_time.tzinfo)
        for c in cumulative[1:]
    ]
    return Timing(
        start=etas[0],
        finish=etas[-1],
        moving_min=pace_factor * base,
        total_min=base * k,
        eta_by_point=etas,
    )
