"""simplify() over pre-thinned candidates and the RDP near-tie rule (ADR 0004 3.5).

The spy tests are the "thinning seam": above 2,000 points RDP must only ever see the
thinned candidates, yet the answer stays exactly 500 full-track indices.
"""

import math
from collections.abc import Callable, Sequence

import pytest

import app.routes.simplify as simplify_module
from app.routes.geo import cumulative_distance
from app.routes.params import EARTH_RADIUS_M
from app.routes.simplify import rdp_significance, simplify
from app.routes.track import RawPoint
from tests.routes.gpx_builders import straight_line

DEG_PER_M = 180.0 / (math.pi * EARTH_RADIUS_M)


class Spy:
    """Records what simplify() hands to prethin and rdp_significance.

    A call that would feed RDP more than 2,000 points raises at once, so a missing
    pre-thinning fails fast instead of running a quadratic RDP for minutes.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.rdp_sizes: list[int] = []
        self.prethin_calls = 0
        real_rdp = simplify_module.rdp_significance
        self._real_prethin = getattr(simplify_module, "prethin", None)

        def rdp(points: Sequence[RawPoint], **kwargs: float) -> tuple[float, ...]:
            self.rdp_sizes.append(len(points))
            if len(points) > 2000:
                raise AssertionError(f"RDP was given {len(points)} points (> 2,000)")
            return real_rdp(points, **kwargs)

        monkeypatch.setattr(simplify_module, "rdp_significance", rdp)
        if self._real_prethin is not None:
            real_prethin: Callable[..., tuple[int, ...]] = self._real_prethin

            def counting(*args: object, **kwargs: object) -> tuple[int, ...]:
                self.prethin_calls += 1
                return real_prethin(*args, **kwargs)

            monkeypatch.setattr(simplify_module, "prethin", counting)


def line(n: int) -> list[RawPoint]:
    return [RawPoint(p.lat, p.lon, p.ele) for p in straight_line(n, step_m=4.0)]


def zigzag(n: int) -> list[RawPoint]:
    """About 9 m sideways swings every 1 m northwards: the quadratic RDP shape."""
    return [
        RawPoint(31.9 + i * 1e-5, 34.9 + (i % 2) * 1e-4, float(i % 7)) for i in range(n)
    ]


def assert_full_track_answer(result: tuple[int, ...], n: int, forced: set[int]) -> None:
    assert len(result) == 500
    assert list(result) == sorted(set(result))
    assert result[0] == 0 and result[-1] == n - 1
    assert forced <= set(result)
    assert all(0 <= i < n for i in result)


# --- the seam -------------------------------------------------------------------------


def test_exactly_2000_points_are_not_thinned(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = Spy(monkeypatch)
    result = simplify(zigzag(2000), keep=[1234])
    assert spy.prethin_calls == 0
    assert spy.rdp_sizes == [2000]
    assert_full_track_answer(result, 2000, {0, 1999, 1234})


@pytest.mark.parametrize("n", [2001, 3000])
def test_just_over_2000_points_reach_rdp_thinned(
    monkeypatch: pytest.MonkeyPatch, n: int
) -> None:
    spy = Spy(monkeypatch)
    result = simplify(zigzag(n), keep=[1234])
    assert spy.rdp_sizes and all(502 <= size <= 2000 for size in spy.rdp_sizes)
    assert_full_track_answer(result, n, {0, n - 1, 1234})


@pytest.mark.parametrize("shape", ["zigzag", "line"])
def test_100k_points_reach_rdp_thinned_and_still_give_500_full_track_indices(
    monkeypatch: pytest.MonkeyPatch, shape: str
) -> None:
    n = 100_000
    points = zigzag(n) if shape == "zigzag" else line(n)
    spy = Spy(monkeypatch)
    result = simplify(points, keep=[77_777])
    assert spy.rdp_sizes and all(502 <= size <= 2000 for size in spy.rdp_sizes)
    assert_full_track_answer(result, n, {0, n - 1, 77_777})
    assert max(i for i in result if i < n - 1) > 2000  # full-track indices, not ranks


def test_the_high_point_survives_thinning_even_when_the_stride_would_skip_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n = 5000
    spy = Spy(monkeypatch)
    # An odd index no stride of ~n/500 or ~L/1500 lands on by chance.
    high = 3137
    result = simplify(line(n), keep=[high])
    assert spy.rdp_sizes
    assert high in result and len(result) == 500


def test_an_explicit_dist_m_is_used_for_thinning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing the full-resolution distance must give the same answer as letting
    simplify compute it, and must reach RDP thinned."""
    points = zigzag(4000)
    dist = cumulative_distance(points)
    spy = Spy(monkeypatch)
    with_dist = simplify(points, keep=[10], dist_m=dist)
    assert all(size <= 2000 for size in spy.rdp_sizes) and spy.rdp_sizes
    assert with_dist == simplify(points, keep=[10])


def test_custom_budgets_thin_at_their_own_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Spy(monkeypatch)
    result = simplify(zigzag(61), max_points=5, prethin_max_points=10)
    assert spy.rdp_sizes and all(7 <= size <= 10 for size in spy.rdp_sizes)
    assert len(result) == 5 and result[0] == 0 and result[-1] == 60


def test_up_to_the_custom_threshold_there_is_no_thinning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Spy(monkeypatch)
    simplify(zigzag(10), max_points=5, prethin_max_points=10)
    assert spy.prethin_calls == 0 and spy.rdp_sizes == [10]


def test_thinning_is_deterministic() -> None:
    points = zigzag(6000)
    assert simplify(points, keep=[42]) == simplify(points, keep=[42])


# --- RDP near-tie split rule (tolerance 1e-6 m, nearest the midpoint, smaller index) --


def bump_line(offsets_m: list[float]) -> list[RawPoint]:
    """Points 0.001 degrees (111 m) apart along the equator; point i sits offsets_m[i]
    metres north of the chord that joins the first and last (both at offset 0)."""
    return [RawPoint(o * DEG_PER_M, i * 0.001, None) for i, o in enumerate(offsets_m)]


def top_interior(points: list[RawPoint]) -> int:
    sig = rdp_significance(points)
    interior = range(1, len(points) - 1)
    return max(interior, key=lambda i: (sig[i], -i))


def test_interior_distances_within_the_tolerance_split_at_the_midpoint() -> None:
    # distances 100 + i*1e-8: the farthest (7) is within 1e-6 of every other one
    offsets = [0.0] + [100.0 + i * 1e-8 for i in range(1, 8)] + [0.0]
    assert top_interior(bump_line(offsets)) == 4


@pytest.mark.parametrize("position", range(1, 8))
def test_a_point_1e5_m_farther_than_the_rest_wins_wherever_it_is(position: int) -> None:
    offsets = [0.0] + [100.0] * 7 + [0.0]
    offsets[position] = 100.0 + 1e-5
    assert top_interior(bump_line(offsets)) == position


def test_equally_near_the_midpoint_the_smaller_index_wins() -> None:
    # 8 points: midpoint 3.5, so 3 and 4 are equally near
    offsets = [0.0, 50.0, 50.0, 100.0, 100.0, 50.0, 50.0, 0.0]
    assert top_interior(bump_line(offsets)) == 3


def test_within_tolerance_and_equally_near_the_midpoint_the_smaller_index_wins() -> (
    None
):
    # 3 is 5e-7 m shallower than 4 (inside the tolerance) and equally near the middle:
    # the smaller index wins although 4 is strictly farther
    offsets = [0.0, 50.0, 50.0, 100.0 - 5e-7, 100.0, 50.0, 50.0, 0.0]
    assert top_interior(bump_line(offsets)) == 3


def test_a_point_nearer_the_midpoint_beats_a_marginally_farther_one() -> None:
    # 5 points, midpoint 2: index 1 is 5e-7 m farther than index 2 (within tolerance),
    # but 2 is nearer the midpoint
    offsets = [0.0, 100.0 + 5e-7, 100.0, 40.0, 0.0]
    assert top_interior(bump_line(offsets)) == 2


def test_the_tolerance_does_not_swallow_a_real_difference() -> None:
    # 2e-6 m farther is outside the 1e-6 tolerance: index 1 wins, not the midpoint
    offsets = [0.0, 100.0 + 2e-6, 100.0, 40.0, 0.0]
    assert top_interior(bump_line(offsets)) == 1
