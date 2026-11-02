"""QA edge cases for the estimator: size extremes, parameter extremes, offset starts,
and a route whose elevation was backfilled by the lookup stage (ADR 0006 §2-§6)."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.models.route import RouteSummary
from app.routes.params import MAX_SUMMARY_POINTS
from app.routes.summary import summarise_gpx, with_looked_up_elevation
from app.timing.estimate import estimate
from app.timing.params import MAX_PACE_FACTOR, MIN_PACE_FACTOR
from tests.elevation_support import TEL_HADID, pair_of, recorded_table
from tests.fixtures.loader import GPX_DIR
from tests.timing.routes import (
    FLAT_SPEED_KMH,
    MIN_PER_M_BOUND,
    START,
    evenly,
    make_route,
)

FIXTURES = [
    "alltrails-tel-hadid-loop",
    "alltrails-modiin-hills-south-double-loop",
    "alltrails-ben-shemen-hertzl-singletrack",
]


def parsed(stem: str) -> RouteSummary:
    path = GPX_DIR / f"{stem}.gpx"
    return summarise_gpx(path.read_bytes(), path.name)


def flat_minutes(metres: float) -> float:
    return 0.06 * metres / FLAT_SPEED_KMH


# --- size ----------------------------------------------------------------------


def test_a_route_at_the_500_point_cap_gets_500_strictly_increasing_etas() -> None:
    dists = evenly(10_000.0, 10_000.0 / (MAX_SUMMARY_POINTS - 1))
    assert len(dists) == MAX_SUMMARY_POINTS
    elevs = [30.0 * (i % 2) for i in range(len(dists))]  # zig-zag noise on every point
    t = estimate(make_route(dists, elevs), START, 1.0, 10.0)
    assert len(t.eta_by_point) == MAX_SUMMARY_POINTS
    assert all(a < b for a, b in zip(t.eta_by_point, t.eta_by_point[1:], strict=False))
    assert t.moving_min <= 0.06 / (6 * math.exp(-3.5 * 0.55)) * 10_000.0


def test_a_100_km_route_is_timed_without_overflow_or_drift() -> None:
    t = estimate(make_route(evenly(100_000.0, 250.0)), START, 1.0, 10.0)
    assert t.moving_min == pytest.approx(flat_minutes(100_000.0), rel=1e-9)
    assert t.finish - t.start == timedelta(minutes=t.total_min)


def test_a_100_000_km_route_at_the_slowest_pace_stays_finite_and_ordered() -> None:
    dists = evenly(1e8, 1e8 / 400)
    t = estimate(make_route(dists), START, MAX_PACE_FACTOR, 60.0)
    assert math.isfinite(t.total_min)
    assert t.total_min == pytest.approx(flat_minutes(1e8) * 4.0 * 2.0, rel=1e-9)
    assert all(a < b for a, b in zip(t.eta_by_point, t.eta_by_point[1:], strict=False))


# --- parameter extremes ----------------------------------------------------------


@pytest.mark.parametrize("stem", FIXTURES)
def test_pace_and_rest_extremes_on_real_routes_differ_by_exactly_the_scale(
    stem: str,
) -> None:
    route = parsed(stem)
    fast = estimate(route, START, MIN_PACE_FACTOR, 0.0)
    slow = estimate(route, START, MAX_PACE_FACTOR, 60.0)
    # (4.0 * 2) / (0.25 * 1) = 32 whatever the terrain
    assert slow.total_min == pytest.approx(32 * fast.total_min, rel=1e-12)
    assert slow.moving_min == pytest.approx(16 * fast.moving_min, rel=1e-12)
    assert fast.total_min == fast.moving_min
    for t in (fast, slow):
        assert len(t.eta_by_point) == len(route.points)
        assert all(
            a < b for a, b in zip(t.eta_by_point, t.eta_by_point[1:], strict=False)
        )
        assert t.eta_by_point[0] == START
        assert t.eta_by_point[-1] == t.finish


def test_rest_60_per_hour_doubles_the_total_on_every_terrain() -> None:
    route = parsed("alltrails-modiin-hills-south-double-loop")
    t = estimate(route, START, 1.0, 60.0)
    assert t.total_min == pytest.approx(2 * t.moving_min, rel=1e-12)


# --- routes that do not start at 0 -------------------------------------------------


@pytest.mark.parametrize("offset", [37.0, 2500.0])
def test_a_hilly_route_shifted_to_start_at_d0_gets_the_same_etas(offset: float) -> None:
    base = [0.0, 3.0, 40.0, 41.0, 180.0, 400.0, 405.0, 900.0, 1000.0]
    elevs = [10.0, 14.0, 14.5, 30.0, 25.0, 90.0, 60.0, 20.0, 20.0]
    zero = estimate(make_route(base, elevs), START, 1.2, 10.0)
    shifted = estimate(make_route([d + offset for d in base], elevs), START, 1.2, 10.0)
    assert shifted.moving_min == pytest.approx(zero.moving_min, rel=1e-9)
    assert [e - START for e in shifted.eta_by_point] == pytest.approx(
        [e - START for e in zero.eta_by_point], abs=timedelta(microseconds=2)
    )


# --- a route backfilled by the lookup stage, through the real pipeline ---------------


def lookup_route() -> RouteSummary:
    path = GPX_DIR / "derived-tel-hadid-no-ele.gpx"
    before = summarise_gpx(path.read_bytes(), path.name)
    table = recorded_table(TEL_HADID)
    values = [table[pair_of(p.lat, p.lon)] for p in before.points]
    return with_looked_up_elevation(before, values)


def test_a_looked_up_route_is_timed_from_its_backfilled_elevation() -> None:
    route = lookup_route()
    assert route.elevation_source == "lookup"
    t = estimate(route, START, 1.0, 10.0)
    flat = flat_minutes(route.distance_m)
    assert t.moving_min != pytest.approx(flat, rel=1e-6)  # elevation was used
    assert 0.97 * flat <= t.moving_min <= 1.20 * flat  # ADR 0006 §8 band
    assert t.moving_min <= MIN_PER_M_BOUND * route.distance_m
    assert len(t.eta_by_point) == len(route.points)
    assert all(a < b for a, b in zip(t.eta_by_point, t.eta_by_point[1:], strict=False))


def test_the_looked_up_route_differs_from_the_same_route_without_elevation() -> None:
    path = GPX_DIR / "derived-tel-hadid-no-ele.gpx"
    none = estimate(summarise_gpx(path.read_bytes(), path.name), START, 1.0, 10.0)
    looked_up = estimate(lookup_route(), START, 1.0, 10.0)
    assert looked_up.moving_min > none.moving_min  # convexity: hills only cost time


# --- start_time near the datetime limits ----------------------------------------------


def test_a_start_one_day_before_datetime_max_is_timed_when_the_finish_fits() -> None:
    start = datetime.max.replace(tzinfo=UTC) - timedelta(days=1)
    t = estimate(make_route(evenly(5000.0, 100.0)), start, 1.0, 10.0)
    assert t.finish - t.start == timedelta(minutes=t.total_min)


def test_the_input_route_is_not_modified() -> None:
    route = parsed("alltrails-tel-hadid-loop")
    before = route.model_dump()
    estimate(route, START, 1.0, 10.0)
    assert route.model_dump() == before
