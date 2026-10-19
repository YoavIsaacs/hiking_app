"""Unit tests for app.routes.geo (haversine, ADR 0004 3.3)."""

import math

import pytest

from app.routes.geo import cumulative_distance, geodesic_distance, is_loop
from app.routes.params import EARTH_RADIUS_M
from app.routes.track import RawPoint


def pt(lat: float, lon: float) -> RawPoint:
    return RawPoint(lat, lon, None)


DEGREE_M = 2 * math.pi * EARTH_RADIUS_M / 360


def test_one_degree_of_latitude_is_about_111_195_m() -> None:
    assert geodesic_distance(pt(0, 0), pt(1, 0)) == pytest.approx(111_195.08, abs=0.01)
    assert round(DEGREE_M, 2) == 111_195.08


def test_one_degree_of_longitude_shrinks_with_the_cosine_of_latitude() -> None:
    d = geodesic_distance(pt(32, 34), pt(32, 35))
    assert d == pytest.approx(DEGREE_M * math.cos(math.radians(32)), rel=1e-4)


def test_tel_aviv_to_jerusalem_is_about_54_km() -> None:
    d = geodesic_distance(pt(32.0853, 34.7818), pt(31.7683, 35.2137))
    assert d == pytest.approx(54_070, rel=5e-3)


def test_distance_is_symmetric_and_zero_for_equal_points() -> None:
    a, b = pt(31.9, 34.9), pt(32.1, 35.2)
    assert geodesic_distance(a, b) == geodesic_distance(b, a)
    assert geodesic_distance(a, a) == 0.0


def test_pairs_across_the_antimeridian_take_the_short_way() -> None:
    d = geodesic_distance(pt(0, 179.5), pt(0, -179.5))
    assert d == pytest.approx(DEGREE_M, rel=1e-9)


def test_antipodal_points_do_not_blow_up() -> None:
    d = geodesic_distance(pt(0, 0), pt(0, 180))
    assert d == pytest.approx(math.pi * EARTH_RADIUS_M, rel=1e-9)


def test_cumulative_distance_is_a_running_sum() -> None:
    pts = [pt(0, 0), pt(1, 0), pt(2, 0), pt(2, 0)]
    cum = cumulative_distance(pts)
    assert cum[0] == 0.0
    assert cum == pytest.approx((0.0, DEGREE_M, 2 * DEGREE_M, 2 * DEGREE_M))


def test_cumulative_distance_of_nothing_and_of_one_point() -> None:
    assert cumulative_distance([]) == ()
    assert cumulative_distance([pt(1, 1)]) == (0.0,)


def test_is_loop_threshold_is_inclusive() -> None:
    a = pt(0, 0)
    b = pt(0.001, 0)
    gap = geodesic_distance(a, b)
    assert is_loop(a, b, threshold_m=gap) is True
    assert is_loop(a, b, threshold_m=gap - 0.001) is False
