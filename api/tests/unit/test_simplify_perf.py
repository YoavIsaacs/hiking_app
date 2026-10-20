"""Regression: RDP work stays bounded on collinear, noisy and adversarial tracks.

The guards count `_segment_distance` calls, the unit of RDP work, instead of reading
the clock: a call count is the same on every machine and fails on the algorithm, not
on a slow runner.
"""

import math
import random
from collections.abc import Callable

import pytest

import app.routes.simplify as simplify_module
from app.routes.params import DEFAULT_PARAMS
from app.routes.simplify import rdp_significance, simplify
from app.routes.summary import summarise_gpx
from app.routes.track import RawPoint

Distance = Callable[
    [tuple[float, float], tuple[float, float], tuple[float, float]], float
]


@pytest.fixture
def distance_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """A one-item counter of `_segment_distance` calls made from now on."""
    calls = [0]
    real: Distance = simplify_module._segment_distance

    def counting(
        p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
    ) -> float:
        calls[0] += 1
        return real(p, a, b)

    monkeypatch.setattr(simplify_module, "_segment_distance", counting)
    return calls


def n_log_n_budget(n: int) -> float:
    """Generous: every level of a perfect halving costs n, plus a factor for slack."""
    return 4 * n * (math.log2(n) + 2)


def diagonal_6dp(n: int) -> list[RawPoint]:
    """A straight diagonal written the way GPX files are: coordinates rounded to 6 dp.

    The rounding (about 5 cm) is real float noise: the points are not exactly
    collinear, and the 1e-6 m tie tolerance does not absorb it.
    """
    return [
        RawPoint(round(31.0 + i * 3.3e-6, 6), round(34.0 + i * 2.1e-6, 6), None)
        for i in range(n)
    ]


def decreasing_zigzag(n: int) -> list[RawPoint]:
    """Swings of shrinking amplitude: the farthest point is always the second one of
    the range, so an un-thinned RDP splits off one point at a time (quadratic)."""
    return [
        RawPoint(
            31.9 + i * 1e-5,
            34.9 + (1 if i % 2 else -1) * 1e-4 * (1 - i / n),
            None,
        )
        for i in range(n)
    ]


def test_ties_split_near_the_midpoint() -> None:
    pts = [RawPoint(i * 1e-4, 0.0, None) for i in range(9)]  # exact ties (d == 0)
    sig = rdp_significance(pts)
    assert math.isinf(sig[0]) and math.isinf(sig[8])
    assert all(s == 0.0 for s in sig[1:8])


def test_exactly_collinear_points_halve_n_log_n(distance_calls: list[int]) -> None:
    n = 20_000
    pts = [RawPoint(i * 1e-6, 0.0, 100.0) for i in range(n)]
    sig = rdp_significance(pts)
    assert len(sig) == n
    assert distance_calls[0] <= n_log_n_budget(n)


@pytest.mark.parametrize("n", [20_000, 100_000])
def test_6dp_rounding_noise_on_a_diagonal_is_bounded_by_the_pre_thinning(
    distance_calls: list[int], n: int
) -> None:
    """The 6 dp rounding is far above the 1e-6 m tolerance, so RDP on the raw points
    is NOT n log n (about 9.4M calls for 20k points measured): only pre-thinning
    bounds it, to the quadratic ceiling of its 2,000 candidates."""
    assert len(simplify(diagonal_6dp(n))) == DEFAULT_PARAMS.max_points
    candidates = DEFAULT_PARAMS.prethin_max_points
    assert distance_calls[0] <= candidates**2 // 2 + candidates


def test_the_tie_tolerance_is_what_keeps_projection_float_noise_cheap(
    distance_calls: list[int],
) -> None:
    """A collinear run with about 1e-9 m of noise (projection float noise): the
    default tolerance halves it (n log n); a zero tolerance does not."""
    n = 5_000
    rng = random.Random(1)
    pts = [RawPoint(rng.uniform(-1e-14, 1e-14), i * 1e-6, None) for i in range(n)]
    rdp_significance(pts)
    with_tolerance = distance_calls[0]
    distance_calls[0] = 0
    rdp_significance(pts, tie_tolerance_m=0.0)
    assert with_tolerance <= n_log_n_budget(n)
    assert distance_calls[0] > 4 * with_tolerance  # the test would notice a no-op


@pytest.mark.parametrize("n", [20_000, 100_000])
def test_simplify_bounds_the_decreasing_zigzag_by_the_pre_thinning(
    distance_calls: list[int], n: int
) -> None:
    """Pre-thinning caps RDP at 2,000 candidates whatever n is, so the worst case is
    the quadratic shape on 2,000 points, not on n."""
    result = simplify(decreasing_zigzag(n))
    assert len(result) == DEFAULT_PARAMS.max_points
    ceiling = DEFAULT_PARAMS.prethin_max_points**2 // 2
    assert distance_calls[0] <= ceiling + DEFAULT_PARAMS.prethin_max_points


def test_simplify_of_100k_collinear_points_is_n_log_n_on_the_candidates(
    distance_calls: list[int],
) -> None:
    pts = [RawPoint(i * 1e-6, 0.0, 100.0) for i in range(100_000)]
    assert len(simplify(pts, max_points=500)) == 500
    assert distance_calls[0] <= n_log_n_budget(DEFAULT_PARAMS.prethin_max_points)


def test_a_gpx_at_the_point_cap_summarises() -> None:
    n = 100_000
    body = "".join(
        f'<trkpt lat="31.0" lon="{34.0 + i * 1e-6:.6f}"><ele>100</ele></trkpt>'
        for i in range(n)
    )
    gpx = (
        '<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{body}</trkseg></trk></gpx>"
    ).encode()
    summary = summarise_gpx(gpx, "line.gpx")
    assert summary.distance_m > 0
    assert summary.point_count_original == n
    assert len(summary.points) == DEFAULT_PARAMS.max_points
