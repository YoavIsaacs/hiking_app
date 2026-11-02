"""Hypothesis invariants of estimate() over generated routes (ADR 0006)."""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.route import RouteSummary
from app.timing.estimate import estimate, segment_slopes
from tests.timing.routes import MIN_PER_M_BOUND, make_route

MOVING_STEP = st.floats(min_value=0.001, max_value=2000.0)
STEP = st.one_of(st.just(0.0), MOVING_STEP)
ELEV = st.floats(min_value=-500.0, max_value=4000.0)
OFFSET = st.floats(min_value=0.0, max_value=5000.0)  # d_0: route need not start at 0


@st.composite
def routes(draw: st.DrawFn, steps_of: st.SearchStrategy[float] = STEP) -> RouteSummary:
    steps = draw(st.lists(steps_of, min_size=1, max_size=60))
    dists = [draw(OFFSET)]
    for step in steps:
        dists.append(dists[-1] + step)
    no_elevation = draw(st.booleans())
    elevs: list[float | None] = [None if no_elevation else draw(ELEV) for _ in dists]
    return make_route(dists, elevs)


@st.composite
def starts(draw: st.DrawFn) -> datetime:
    offset = draw(st.integers(min_value=-14 * 60, max_value=14 * 60))
    naive = draw(
        st.datetimes(min_value=datetime(2000, 1, 2), max_value=datetime(2099, 12, 30))
    )
    return naive.replace(tzinfo=timezone(timedelta(minutes=offset)))


PACE = st.floats(min_value=0.25, max_value=4.0)
REST = st.floats(min_value=0.0, max_value=60.0)
COMMON = settings(max_examples=150, deadline=None)


@COMMON
@given(routes(), starts(), PACE, REST)
def test_one_eta_per_point(
    route: RouteSummary, start: datetime, pace: float, rest: float
) -> None:
    assert len(estimate(route, start, pace, rest).eta_by_point) == len(route.points)


@COMMON
@given(routes(), starts(), PACE, REST)
def test_etas_never_decrease_and_increase_where_distance_does(
    route: RouteSummary, start: datetime, pace: float, rest: float
) -> None:
    etas = estimate(route, start, pace, rest).eta_by_point
    for i in range(len(etas) - 1):
        assert etas[i] <= etas[i + 1]
        if route.points[i + 1].dist_m - route.points[i].dist_m >= 0.001:
            assert etas[i] < etas[i + 1]


@COMMON
@given(routes(), starts(), PACE, REST)
def test_total_at_least_moving_at_least_zero(
    route: RouteSummary, start: datetime, pace: float, rest: float
) -> None:
    t = estimate(route, start, pace, rest)
    assert t.total_min >= t.moving_min >= 0.0


@COMMON
@given(routes(), starts(), PACE, REST)
def test_moving_time_stays_under_the_clamp_bound(
    route: RouteSummary, start: datetime, pace: float, rest: float
) -> None:
    length = route.points[-1].dist_m - route.points[0].dist_m
    bound = pace * MIN_PER_M_BOUND * length
    assert estimate(route, start, pace, rest).moving_min <= bound * (1 + 1e-9)


@COMMON
@given(routes(), starts(), PACE, REST)
def test_first_and_last_eta_are_start_and_finish(
    route: RouteSummary, start: datetime, pace: float, rest: float
) -> None:
    t = estimate(route, start, pace, rest)
    assert t.eta_by_point[0] == start == t.start
    assert t.eta_by_point[-1] == t.finish
    assert abs((t.finish - t.start) - timedelta(minutes=t.total_min)) <= timedelta(
        microseconds=1
    )


@COMMON
@given(routes(), starts(), PACE, REST)
def test_same_input_gives_equal_output(
    route: RouteSummary, start: datetime, pace: float, rest: float
) -> None:
    assert estimate(route, start, pace, rest) == estimate(route, start, pace, rest)


@COMMON
@given(routes(), starts(), REST, PACE)
def test_moving_time_scales_exactly_with_pace(
    route: RouteSummary, start: datetime, rest: float, pace: float
) -> None:
    base = estimate(route, start, 1.0, rest).moving_min
    assert estimate(route, start, pace, rest).moving_min == pace * base


@COMMON
# No zero-length steps here: a repeated distance with a different elevation is a
# step in E(x), where a one-ulp change in the shifted window edge flips the slope.
@given(
    routes(MOVING_STEP),
    starts(),
    PACE,
    REST,
    st.floats(min_value=0.0, max_value=100_000.0),
)
def test_shifting_every_distance_changes_neither_times_nor_etas(
    route: RouteSummary, start: datetime, pace: float, rest: float, shift: float
) -> None:
    shifted = route.model_copy(
        update={
            "points": [
                p.model_copy(update={"dist_m": p.dist_m + shift}) for p in route.points
            ]
        }
    )
    a = estimate(route, start, pace, rest)
    b = estimate(shifted, start, pace, rest)
    assert b.moving_min == pytest.approx(a.moving_min, rel=1e-9, abs=1e-9)
    assert b.total_min == pytest.approx(a.total_min, rel=1e-9, abs=1e-9)
    for x, y in zip(a.eta_by_point, b.eta_by_point, strict=True):
        assert abs(x - y) <= timedelta(milliseconds=1)


@COMMON
@given(routes())
def test_slopes_are_clamped_and_one_per_segment(route: RouteSummary) -> None:
    slopes = segment_slopes(route.points)
    assert len(slopes) == len(route.points) - 1
    assert all(-0.5 <= s <= 0.5 for s in slopes)
