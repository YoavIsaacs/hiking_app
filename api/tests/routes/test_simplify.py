"""simplify(): output cap, forced points, no recursion (ADR 0004 3.5)."""

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from app.routes.simplify import rdp_significance, simplify
from app.routes.track import RawPoint
from tests.routes.gpx_builders import Pt, destination, straight_line


def raw(points: list[Pt]) -> list[RawPoint]:
    return [RawPoint(p.lat, p.lon, p.ele) for p in points]


def wiggly(n: int) -> list[RawPoint]:
    pts = [Pt(31.9, 34.9, 0.0)]
    for i in range(1, n):
        pts.append(destination(pts[-1], (i * 37) % 360, 8.0 + (i % 5)))
    return raw(pts)


def test_up_to_500_points_are_returned_unchanged() -> None:
    for n in (2, 3, 499, 500):
        assert simplify(wiggly(n)) == tuple(range(n))


def test_more_than_500_points_give_exactly_500_sorted_indices() -> None:
    result = simplify(wiggly(501))
    assert len(result) == 500
    assert list(result) == sorted(set(result))
    assert result[0] == 0 and result[-1] == 500


def test_start_end_and_forced_points_are_kept_even_when_rdp_would_drop_them() -> None:
    pts = raw(straight_line(3000, step_m=4.0))
    result = simplify(pts, keep=[1777])
    assert len(result) == 500
    assert {0, 2999, 1777} <= set(result)


def test_forced_indices_count_against_the_budget() -> None:
    pts = wiggly(2000)
    keep = [10, 500, 1500]
    result = simplify(pts, keep=keep, max_points=50)
    assert len(result) == 50
    assert {0, 1999, *keep} <= set(result)


def test_loop_with_coinciding_start_and_end_is_simplified() -> None:
    out = wiggly(700)
    loop = [*out, out[0]]
    result = simplify(loop)
    assert len(result) == 500
    assert result[0] == 0 and result[-1] == 700


def test_a_straight_line_longer_than_the_recursion_limit_is_simplified() -> None:
    result = simplify(raw(straight_line(5000, step_m=2.0)))
    assert len(result) == 500


def test_a_spiral_is_simplified_without_recursion_errors() -> None:
    pts = [Pt(31.9, 34.9, 0.0)]
    for i in range(3000):
        pts.append(destination(pts[-1], (i * 0.7) % 360, 3.0 + i * 0.01))
    assert len(simplify(raw(pts))) == 500


def test_the_most_significant_bend_survives() -> None:
    line = straight_line(1000, step_m=5.0)
    bent = [*line[:500], *(destination(p, 90.0, 300.0) for p in line[500:])]
    result = simplify(raw(bent), max_points=5)
    assert len(result) == 5
    assert 499 in result or 500 in result


def test_rdp_significance_is_infinite_at_both_ends_and_finite_elsewhere() -> None:
    sig = rdp_significance(wiggly(50))
    assert len(sig) == 50
    assert math.isinf(sig[0]) and math.isinf(sig[-1])
    assert all(math.isfinite(s) and s >= 0 for s in sig[1:-1])


@settings(max_examples=40, deadline=None, derandomize=True)
@given(
    st.integers(2, 900),
    st.integers(3, 500),
    st.data(),
)
def test_output_is_sorted_unique_sized_and_contains_forced_points(
    n: int, cap: int, data: st.DataObject
) -> None:
    pts = wiggly(n)
    forced = data.draw(st.lists(st.integers(0, n - 1), max_size=min(5, cap - 2)))
    result = simplify(pts, keep=forced, max_points=cap)
    assert len(result) == min(n, cap)
    assert list(result) == sorted(set(result))
    assert {0, n - 1, *forced} <= set(result)
