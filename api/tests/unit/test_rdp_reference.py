"""rdp_significance against a naive recursive RDP reference (ADR 0004 3.5)."""

import math
import random
from collections.abc import Callable

import pytest

from app.routes.params import RDP_TIE_TOLERANCE_M
from app.routes.simplify import (
    _project,  # same metric as the code under test; the recursion below is independent
    _segment_distance,
    rdp_significance,
    simplify,
)
from app.routes.track import RawPoint


def walk(n: int, seed: int) -> list[RawPoint]:
    rng = random.Random(seed)
    lat, lon = 31.9, 34.9
    pts = [RawPoint(lat, lon, None)]
    for _ in range(n - 1):
        lat += rng.uniform(-0.0004, 0.0005)
        lon += rng.uniform(-0.0004, 0.0006)
        pts.append(RawPoint(lat, lon, None))
    return pts


def naive_rdp(points: list[RawPoint], eps: float) -> set[int]:
    """Textbook recursive RDP with the ADR 3.5 split rule; returns the kept indices.

    Split rule: among the interior points within RDP_TIE_TOLERANCE_M of the farthest,
    take the one nearest the midpoint (smaller index on a tie). The range is split
    only if that point's own distance is > eps.
    """
    xy = _project(points)
    keep = {0, len(points) - 1}

    def rec(a: int, b: int) -> None:
        if b - a < 2:
            return
        d = {i: _segment_distance(xy[i], xy[a], xy[b]) for i in range(a + 1, b)}
        floor = max(d.values()) - RDP_TIE_TOLERANCE_M
        mid = (a + b) / 2
        far = min((i for i in d if d[i] >= floor), key=lambda i: (abs(i - mid), i))
        if d[far] > eps:
            keep.add(far)
            rec(a, far)
            rec(far, b)

    rec(0, len(points) - 1)
    return keep


def coarse_walk(n: int, seed: int) -> list[RawPoint]:
    """A walk on a 1e-4 degree grid (about 11 m): many exact and near distance ties."""
    return [RawPoint(round(p.lat, 4), round(p.lon, 4), None) for p in walk(n, seed)]


@pytest.mark.parametrize("make", [walk, coarse_walk], ids=["walk", "coarse-grid"])
@pytest.mark.parametrize("seed", range(12))
def test_significance_thresholds_reproduce_rdp_for_every_epsilon(
    seed: int, make: Callable[[int, int], list[RawPoint]]
) -> None:
    pts = make(5 + seed * 7, seed)
    sig = rdp_significance(pts)
    finite = sorted({s for s in sig if math.isfinite(s)})
    epsilons = [0.0, *finite, *(f * 1.0001 for f in finite), 1e9]
    for eps in epsilons:
        ranked = {i for i, s in enumerate(sig) if s > eps}
        assert ranked == naive_rdp(pts, eps), (seed, eps)


def test_tiny_inputs_have_infinite_significance_everywhere() -> None:
    assert rdp_significance([]) == ()
    one = [RawPoint(1.0, 1.0, None)]
    assert rdp_significance(one) == (math.inf,)
    two = [*one, RawPoint(1.1, 1.1, None)]
    assert rdp_significance(two) == (math.inf, math.inf)


def test_a_track_across_the_antimeridian_is_projected_continuously() -> None:
    pts = [
        RawPoint(0.0, 179.99, None),
        RawPoint(0.001, -179.995, None),
        RawPoint(0.0, -179.99, None),
    ]
    sig = rdp_significance(pts)
    assert 0 < sig[1] < 200  # a ~110 m bump, not a 40 000 km detour


def test_more_forced_points_than_the_budget_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        simplify(walk(20, 1), keep=[3, 4, 5], max_points=4)
