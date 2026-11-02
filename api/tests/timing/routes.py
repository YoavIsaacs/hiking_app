"""Builders for timing tests: RouteSummary values from distance/elevation lists."""

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Final

from app.models.route import LatLonElev, RouteSummary, TrackPoint

START: Final = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
FLAT_SPEED_KMH: Final = 6.0 * math.exp(-3.5 * 0.05)  # Tobler at slope 0, ADR 0006 §1
FLAT_5KM_MOVING_MIN: Final = 59.5623  # ADR 0006 §1
FLAT_5KM_TOTAL_MIN: Final = 69.4894  # ... at rest 10 min/h
# ADR 0006 §2 bound (68.55 min/km): pace-1 minutes per metre at the clamp
MIN_PER_M_BOUND: Final = 0.06 / (6.0 * math.exp(-3.5 * 0.55))


def make_route(
    dists: Sequence[float],
    elevs: Sequence[float | None] | None = None,
    name: str = "synthetic",
) -> RouteSummary:
    """A RouteSummary over cumulative distances; flat at 100 m if elevs is None."""
    values: Sequence[float | None] = (
        elevs if elevs is not None else [100.0] * len(dists)
    )
    assert len(values) == len(dists)
    points = [
        TrackPoint(lat=32.0, lon=34.0, elev_m=e, dist_m=d)
        for d, e in zip(dists, values, strict=True)
    ]
    has_elevation = all(e is not None for e in values)
    first, last = points[0], points[-1]
    return RouteSummary(
        name=name,
        distance_m=last.dist_m,
        gain_m=None,
        loss_m=None,
        min_elev_m=None,
        max_elev_m=None,
        high_point=None,
        start=LatLonElev(lat=first.lat, lon=first.lon, elev_m=first.elev_m),
        end=LatLonElev(lat=last.lat, lon=last.lon, elev_m=last.elev_m),
        is_loop=False,
        points=points,
        has_elevation=has_elevation,
        elevation_source="file" if has_elevation else "none",
        source_format="trk",
        point_count_original=max(2, len(points)),
        warnings=[],
    )


def evenly(total_m: float, step_m: float) -> list[float]:
    """Cumulative distances 0, step, 2*step ... ending exactly at total_m."""
    count = round(total_m / step_m)
    return [total_m * i / count for i in range(count + 1)]


def flat_5km(step_m: float = 12.5, elev: float | None = 100.0) -> RouteSummary:
    dists = evenly(5000.0, step_m)
    return make_route(dists, [elev] * len(dists))


def uniform_slope(
    total_m: float, slope: float, step_m: float | None = None
) -> RouteSummary:
    dists = evenly(total_m, step_m or total_m)
    return make_route(dists, [slope * d for d in dists])


def spike_distances(with_spike: bool) -> list[float]:
    """ADR 0006 §2 spike layout (kept under the 500-point cap): 10 m spacing around
    2.4-2.6 km, 100 m elsewhere, plus an extra point at 2502 m when with_spike."""
    coarse_a = [100.0 * i for i in range(25)]  # 0 .. 2400
    fine = [2400.0 + 10.0 * i for i in range(1, 21)]  # 2410 .. 2600
    coarse_b = [2600.0 + 100.0 * i for i in range(1, 25)]  # 2700 .. 5000
    dists = coarse_a + fine + coarse_b
    if with_spike:
        dists.append(2502.0)
        dists.sort()
    return dists


def spike_route(with_spike: bool) -> RouteSummary:
    dists = spike_distances(with_spike)
    return make_route(dists, [30.0 if d == 2502.0 else 0.0 for d in dists])


class SwitchingZone(tzinfo):
    """A tz with one forward 1 h jump at a UTC instant (stands in for Jerusalem DST).

    Windows has no tz database without the tzdata package, which is not a project
    dependency; this reproduces the property that matters: wall-clock arithmetic
    across the jump is 1 h wrong, instant arithmetic is right.
    """

    def __init__(self, switch_utc: datetime, before_h: int = 2) -> None:
        self._switch_utc = switch_utc.replace(tzinfo=None)
        self._before = timedelta(hours=before_h)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        assert dt is not None
        wall_switch = self._switch_utc + self._before
        extra = (
            timedelta(hours=1)
            if dt.replace(tzinfo=None) >= wall_switch
            else timedelta(0)
        )
        return self._before + extra

    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> str:
        return "SWITCH"

    def fromutc(self, dt: datetime) -> datetime:
        extra = (
            timedelta(hours=1)
            if dt.replace(tzinfo=None) >= self._switch_utc
            else timedelta(0)
        )
        return dt + self._before + extra
