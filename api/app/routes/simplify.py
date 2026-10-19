"""Ranked Ramer-Douglas-Peucker simplification (ADR 0004 §3.5)."""

import math
from bisect import bisect_left
from collections.abc import Collection, Sequence

from app.routes.geo import cumulative_distance
from app.routes.params import DEFAULT_PARAMS, EARTH_RADIUS_M, RDP_TIE_TOLERANCE_M
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


def prethin(
    dist_m: Sequence[float],
    *,
    keep: Collection[int] = (),
    min_points: int = DEFAULT_PARAMS.max_points,
    max_points: int = DEFAULT_PARAMS.prethin_max_points,
) -> tuple[int, ...]:
    """O(n) pre-thinning to at most max_points candidate indices (ADR 0004 3.5).

    Forced indices F = {0, n-1} + keep, M = min_points. M evenly strided interior
    indices guarantee at least M + 2 candidates; the rest of the budget goes to
    indices at evenly spaced distances, so sparse stretches of a dense recording
    survive.
    """
    if min_points < 1 or max_points < 2 * min_points:
        raise ValueError("max_points must be at least 2 * min_points")
    n = len(dist_m)
    if n <= max_points:
        return tuple(range(n))
    forced = {0, n - 1, *keep}
    if len(forced) > min_points:
        raise ValueError("more forced points than min_points")
    picks = set(forced)
    picks.update(1 + j * (n - 2) // min_points for j in range(min_points))
    total = dist_m[-1]
    spare = max_points - len(forced) - min_points
    if total > 0 and spare > 0:
        for j in range(1, spare + 1):
            picks.add(bisect_left(dist_m, j * total / (spare + 1)))
    return tuple(sorted(picks))


def rdp_significance(
    points: Sequence[RawPoint], *, tie_tolerance_m: float = RDP_TIE_TOLERANCE_M
) -> tuple[float, ...]:
    """inf at both ends; iterative, no recursion.

    Splitting (a, b) at a point i gives sig(i) = min(d_i, sig(parent)), so
    {i : sig(i) > eps} is exactly the output of RDP(eps) for every eps. The split
    point is the one nearest the midpoint among those within tie_tolerance_m of the
    farthest (smaller index on a tie): collinear runs halve (m log m, not m^2).
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
        dists = [_segment_distance(xy[i], pa, pb) for i in range(a + 1, b)]
        floor = max(dists) - tie_tolerance_m
        mid = (a + b) / 2
        far = min(
            (i for i in range(a + 1, b) if dists[i - a - 1] >= floor),
            key=lambda i: (abs(i - mid), i),
        )
        sig[far] = min(dists[far - a - 1], parent)
        stack.append((a, far, sig[far]))
        stack.append((far, b, sig[far]))
    return tuple(sig)


def simplify(
    points: Sequence[RawPoint],
    *,
    keep: Collection[int] = (),
    max_points: int = DEFAULT_PARAMS.max_points,
    prethin_max_points: int = DEFAULT_PARAMS.prethin_max_points,
    dist_m: Sequence[float] | None = None,
) -> tuple[int, ...]:
    """Sorted indices, len == min(n, max_points); start, end and `keep` stay in.

    Above prethin_max_points, RDP ranks only the pre-thinned candidates; the result
    still holds full-track indices.
    """
    n = len(points)
    if n <= max_points:
        return tuple(range(n))
    forced = {0, n - 1, *keep}
    if len(forced) > max_points:
        raise ValueError("more forced points than the point budget")
    if n > prethin_max_points:
        full_dist = cumulative_distance(points) if dist_m is None else dist_m
        candidates = prethin(
            full_dist,
            keep=forced,
            min_points=max_points,
            max_points=prethin_max_points,
        )
    else:
        candidates = tuple(range(n))
    sig = rdp_significance([points[i] for i in candidates])
    rest = sorted(
        (k for k, i in enumerate(candidates) if i not in forced),
        key=lambda k: (-sig[k], candidates[k]),
    )
    chosen = {candidates[k] for k in rest[: max_points - len(forced)]}
    return tuple(sorted(forced | chosen))
