"""Distance and loop detection (haversine, metres, 2-D; ADR 0004 §3.3)."""

import math
from collections.abc import Sequence

from app.routes.params import DEFAULT_PARAMS, EARTH_RADIUS_M
from app.routes.track import RawPoint


def geodesic_distance(a: RawPoint, b: RawPoint) -> float:
    """Haversine distance in metres on a sphere of radius EARTH_RADIUS_M."""
    phi_a = math.radians(a.lat)
    phi_b = math.radians(b.lat)
    d_phi = phi_b - phi_a
    d_lambda = math.radians(b.lon) - math.radians(a.lon)
    h = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def cumulative_distance(points: Sequence[RawPoint]) -> tuple[float, ...]:
    """[0.0, ...] with len == len(points): a running float sum of the steps."""
    if not points:
        return ()
    out = [0.0]
    total = 0.0
    for a, b in zip(points, points[1:], strict=False):
        total += geodesic_distance(a, b)
        out.append(total)
    return tuple(out)


def is_loop(
    start: RawPoint,
    end: RawPoint,
    *,
    threshold_m: float = DEFAULT_PARAMS.loop_threshold_m,
) -> bool:
    """True when the ends are within threshold_m (inclusive)."""
    return geodesic_distance(start, end) <= threshold_m
