"""Hypothesis invariants of estimate() over generated routes (ADR 0006)."""

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.route import RouteSummary
from app.timing.estimate import estimate, segment_slopes
from tests.timing.routes import MIN_PER_M_BOUND, make_route

STEP = st.one_of(st.just(0.0), st.floats(min_value=0.001, max_value=2000.0))
ELEV = st.floats(min_value=-500.0, max_value=4000.0)


@st.composite
def routes(draw: st.DrawFn) -> RouteSummary:
    steps = draw(st.lists(STEP, min_size=1, max_size=60))
    dists = [0.0]
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
    bound = pace * MIN_PER_M_BOUND * route.points[-1].dist_m
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
@given(routes())
def test_slopes_are_clamped_and_one_per_segment(route: RouteSummary) -> None:
    slopes = segment_slopes(route.points)
    assert len(slopes) == len(route.points) - 1
    assert all(-0.5 <= s <= 0.5 for s in slopes)
