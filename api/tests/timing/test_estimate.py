"""estimate(): moving/total time, pace, rest, missing elevation, preconditions."""

import math
from datetime import UTC, datetime, timedelta, tzinfo

import pytest

from app.config import Settings
from app.models.route import RouteSummary
from app.timing.estimate import estimate
from tests.timing.routes import (
    FLAT_5KM_MOVING_MIN,
    FLAT_5KM_TOTAL_MIN,
    FLAT_SPEED_KMH,
    START,
    evenly,
    flat_5km,
    make_route,
    uniform_slope,
)


def moving(route: RouteSummary, pace: float = 1.0, rest: float = 0.0) -> float:
    return estimate(route, START, pace, rest).moving_min


def wavy(total_m: float = 3000.0, amplitude: float = 15.0) -> RouteSummary:
    dists = evenly(total_m, 100.0)
    return make_route(dists, [amplitude * math.sin(d / 200.0) for d in dists])


@pytest.mark.parametrize("step", [5000.0, 12.5, 100.0])
@pytest.mark.parametrize("elev", [100.0, 0.0, None])
def test_flat_5km_matches_tobler_at_zero_slope(step: float, elev: float | None) -> None:
    t = estimate(flat_5km(step, elev), START, 1.0, 0.0)
    assert t.moving_min == pytest.approx(FLAT_5KM_MOVING_MIN, rel=1e-5)
    assert t.total_min == pytest.approx(FLAT_5KM_MOVING_MIN, rel=1e-5)


def test_flat_5km_with_default_rest_is_69_49_minutes() -> None:
    t = estimate(flat_5km(), START, 1.0, 10.0)
    assert t.moving_min == pytest.approx(FLAT_5KM_MOVING_MIN, rel=1e-5)
    assert t.total_min == pytest.approx(FLAT_5KM_TOTAL_MIN, rel=1e-5)


@pytest.mark.parametrize(
    ("slope", "kmh"),
    [
        (0.10, 3.54933),
        (-0.05, 6.0),
        (-0.10, 5.03674),
        (0.20, 2.50117),
        (-0.30, 2.50117),
        (0.30, 1.76255),
    ],
)
def test_uniform_slope_route_takes_distance_over_tobler_speed(
    slope: float, kmh: float
) -> None:
    route = uniform_slope(2000.0, slope, step_m=50.0)
    assert moving(route) == pytest.approx(0.06 * 2000.0 / kmh, rel=1e-5)


def test_steep_uphill_is_slower_than_flat() -> None:
    assert moving(uniform_slope(1000.0, 0.2, 50.0)) > moving(
        uniform_slope(1000.0, 0.0, 50.0)
    )


def test_gentle_downhill_is_faster_than_flat() -> None:
    assert moving(uniform_slope(1000.0, -0.05, 50.0)) < moving(
        uniform_slope(1000.0, 0.0, 50.0)
    )


def test_steep_downhill_is_slower_than_flat() -> None:
    assert moving(uniform_slope(1000.0, -0.3, 50.0)) > moving(
        uniform_slope(1000.0, 0.0, 50.0)
    )


def test_extreme_uphill_is_clamped_to_50_percent() -> None:
    route = make_route([0.0, 100.0], [0.0, 80.0])
    assert moving(route) == pytest.approx(0.06 * 100.0 / 0.875254, rel=1e-5)  # 6.8552


def test_extreme_downhill_is_clamped_to_minus_50_percent() -> None:
    route = make_route([0.0, 100.0], [80.0, 0.0])
    assert moving(route) == pytest.approx(0.06 * 100.0 / 1.242044, rel=1e-5)  # 4.8307


def test_pace_factor_scales_moving_time_exactly() -> None:
    route = wavy()
    assert moving(route, 1.5) == 1.5 * moving(route, 1.0)


@pytest.mark.parametrize("rest", [0.0, 10.0, 60.0])
@pytest.mark.parametrize("pace", [0.25, 0.7, 1.5, 4.0])
def test_pace_factor_scales_total_time_linearly(pace: float, rest: float) -> None:
    route = wavy()
    base = estimate(route, START, 1.0, rest).total_min
    assert estimate(route, START, pace, rest).total_min == pytest.approx(
        pace * base, rel=1e-12
    )


@pytest.mark.parametrize("rest", [0.0, 10.0, 30.0, 60.0])
def test_rest_adds_minutes_per_moving_hour(rest: float) -> None:
    t = estimate(flat_5km(), START, 1.5, rest)
    assert t.total_min == pytest.approx(t.moving_min * (1 + rest / 60.0), rel=1e-12)


def test_zero_distance_route_takes_zero_minutes() -> None:
    t = estimate(make_route([0.0, 0.0]), START, 1.0, 10.0)
    assert (t.moving_min, t.total_min) == (0.0, 0.0)
    assert t.start == t.finish == START
    assert t.eta_by_point == [START, START]


def test_zero_distance_route_with_many_points_has_all_etas_at_start() -> None:
    elevs: list[float | None] = [1.0, 9.0, 2.0, 8.0, 3.0, 7.0, 4.0]
    t = estimate(make_route([0.0] * 7, elevs), START, 2.0, 30.0)
    assert t.total_min == 0.0
    assert t.eta_by_point == [START] * 7


def test_repeated_point_adds_no_time() -> None:
    plain = moving(make_route([0.0, 500.0, 1000.0], [0.0, 50.0, 100.0]))
    doubled = moving(make_route([0.0, 500.0, 500.0, 1000.0], [0.0, 50.0, 50.0, 100.0]))
    assert doubled == pytest.approx(plain, rel=1e-9)


# ---- missing elevation (ADR 0006 §3) ----


def test_route_without_elevation_is_timed_flat() -> None:
    dists = evenly(4000.0, 80.0)
    wiggly = make_route(dists, [50.0 * math.sin(d / 100.0) for d in dists])
    none = make_route(dists, [None] * len(dists))
    flat = make_route(dists, [7.0] * len(dists))
    assert none.elevation_source == "none"
    assert estimate(none, START, 1.0, 10.0) == estimate(flat, START, 1.0, 10.0)
    assert moving(none) < moving(wiggly)


def test_one_missing_elevation_makes_the_whole_route_flat() -> None:
    dists = evenly(4000.0, 80.0)
    elevs: list[float | None] = [0.3 * d for d in dists]
    elevs[17] = None
    partial = make_route(dists, elevs)
    flat = make_route(dists, [0.0] * len(dists))
    assert estimate(partial, START, 1.0, 10.0) == estimate(flat, START, 1.0, 10.0)


def test_missing_elevation_is_read_from_the_points_not_the_flags() -> None:
    dists = evenly(2000.0, 100.0)
    elevs: list[float | None] = [0.4 * d if i else None for i, d in enumerate(dists)]
    forged = make_route(dists, elevs).model_copy(
        update={"has_elevation": True, "elevation_source": "file"}
    )
    assert moving(forged) == pytest.approx(0.06 * 2000.0 / FLAT_SPEED_KMH, rel=1e-9)


# ---- preconditions (ADR 0006 §4, §6) ----


class NoOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return None


@pytest.mark.parametrize(
    "start",
    [datetime(2026, 6, 1, 6, 0), datetime(2026, 6, 1, 6, 0, tzinfo=NoOffset())],
    ids=["naive", "tzinfo-without-offset"],
)
def test_naive_start_time_is_rejected(start: datetime) -> None:
    with pytest.raises(ValueError):
        estimate(flat_5km(), start, 1.0, 10.0)


@pytest.mark.parametrize("pace", [0.2, 0.0, -1.0, 4.1, math.nan, math.inf, -math.inf])
def test_out_of_range_pace_is_rejected(pace: float) -> None:
    with pytest.raises(ValueError):
        estimate(flat_5km(), START, pace, 10.0)


@pytest.mark.parametrize("rest", [-1.0, 61.0, math.nan, math.inf, -math.inf])
def test_out_of_range_rest_is_rejected(rest: float) -> None:
    with pytest.raises(ValueError):
        estimate(flat_5km(), START, 1.0, rest)


@pytest.mark.parametrize(
    ("pace", "rest"), [(0.25, 0.0), (4.0, 60.0), (0.25, 60.0), (4.0, 0.0)]
)
def test_boundary_pace_and_rest_are_accepted(pace: float, rest: float) -> None:
    t = estimate(flat_5km(), START, pace, rest)
    assert t.total_min == pytest.approx(
        FLAT_5KM_MOVING_MIN * pace * (1 + rest / 60.0), rel=1e-5
    )


def test_decreasing_distance_is_rejected() -> None:
    with pytest.raises(ValueError):
        estimate(make_route([0.0, 100.0, 50.0]), START, 1.0, 10.0)


def test_time_comes_from_point_distances_not_route_distance_m() -> None:
    route = flat_5km()
    liar = route.model_copy(update={"distance_m": 1.0})
    assert estimate(liar, START, 1.0, 10.0) == estimate(route, START, 1.0, 10.0)


def test_same_input_gives_equal_output() -> None:
    route = wavy()
    assert estimate(route, START, 1.2, 10.0) == estimate(route, START, 1.2, 10.0)


def test_settings_defaults_feed_estimate_end_to_end() -> None:
    s = Settings(_env_file=None)
    start = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
    t = estimate(flat_5km(), start, s.pace_factor, s.rest_min_per_hour)
    assert t.total_min == pytest.approx(FLAT_5KM_TOTAL_MIN, rel=1e-5)
