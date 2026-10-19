"""Ranked Ramer-Douglas-Peucker simplification (ADR 0004 §3.5)."""

import math
from collections.abc import Collection, Sequence

from app.routes.params import DEFAULT_PARAMS, EARTH_RADIUS_M
from app.routes.track import RawPoint


def _project(points: Sequence[RawPoint]) -> list[tuple[float, float]]:
    """Local equirectangular projection to metres, relative to the first point."""
    lats = [p.lat for p in points]
    cos_mid = math.cos(math.radians((min(lats) + max(lats)) / 2))
    first = points[0]
    out: list[tuple[float, float]] = []
    for p in points:
        d_lon = (p.lon - first.lon + 180.0) % 360.0 - 180.0
        out.append(
            (
                EARTH_RADIUS_M * cos_mid * math.radians(d_lon),
                EARTH_RADIUS_M * math.radians(p.lat - first.lat),
            )
        )
    return out


def _segment_distance(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Distance from p to the segment a-b (to a when the segment is degenerate)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def rdp_significance(points: Sequence[RawPoint]) -> tuple[float, ...]:
    """inf at both ends; iterative, no recursion.

    Splitting (a, b) at the farthest point i gives sig(i) = min(d_max, sig(parent)),
    so {i : sig(i) > eps} is exactly the output of RDP(eps) for every eps.
    """
    n = len(points)
    sig = [math.inf] * n
    if n < 3:
        return tuple(sig)
    xy = _project(points)
    stack: list[tuple[int, int, float]] = [(0, n - 1, math.inf)]
    while stack:
        a, b, parent = stack.pop()
        if b - a < 2:
            continue
        pa, pb = xy[a], xy[b]
        # Ties split nearest the midpoint: collinear runs halve (n log n, not n^2).
        mid = (a + b) / 2
        far, far_d = a + 1, -1.0
        for i in range(a + 1, b):
            d = _segment_distance(xy[i], pa, pb)
            if d > far_d or (d == far_d and abs(i - mid) < abs(far - mid)):
                far, far_d = i, d
        sig[far] = min(far_d, parent)
        stack.append((a, far, sig[far]))
        stack.append((far, b, sig[far]))
    return tuple(sig)


def simplify(
    points: Sequence[RawPoint],
    *,
    keep: Collection[int] = (),
    max_points: int = DEFAULT_PARAMS.max_points,
) -> tuple[int, ...]:
    """Sorted indices, len == min(n, max_points); start, end and `keep` stay in."""
    n = len(points)
    if n <= max_points:
        return tuple(range(n))
    forced = {0, n - 1, *keep}
    if len(forced) > max_points:
        raise ValueError("more forced points than the point budget")
    sig = rdp_significance(points)
    rest = sorted((i for i in range(n) if i not in forced), key=lambda i: (-sig[i], i))
    return tuple(sorted(forced | set(rest[: max_points - len(forced)])))
