"""ETAs: first = start, last = finish, strictly increasing, DST (ADR 0006 §5)."""

from datetime import UTC, datetime, timedelta, timezone

from app.timing.estimate import estimate
from tests.timing.routes import (
    FLAT_SPEED_KMH,
    START,
    SwitchingZone,
    evenly,
    flat_5km,
    make_route,
)

ONE_MICROSECOND = timedelta(microseconds=1)


def test_first_eta_is_start_and_last_is_finish() -> None:
    t = estimate(flat_5km(), START, 1.0, 10.0)
    assert t.eta_by_point[0] == START
    assert t.start == START
    assert t.finish == t.eta_by_point[-1]


def test_one_eta_per_point() -> None:
    route = flat_5km(50.0)
    assert len(estimate(route, START, 1.0, 10.0).eta_by_point) == len(route.points)


def test_etas_are_strictly_increasing_on_a_normal_route() -> None:
    etas = estimate(flat_5km(12.5), START, 1.0, 10.0).eta_by_point
    assert all(a < b for a, b in zip(etas, etas[1:], strict=False))


def test_etas_strictly_increase_across_millimetre_steps_at_the_fastest_pace() -> None:
    dists = [0.001 * i for i in range(50)]
    etas = estimate(make_route(dists), START, 0.25, 0.0).eta_by_point
    assert all(a < b for a, b in zip(etas, etas[1:], strict=False))


def test_etas_do_not_move_across_a_repeated_point() -> None:
    t = estimate(make_route([0.0, 500.0, 500.0, 900.0]), START, 1.0, 10.0)
    assert t.eta_by_point[1] == t.eta_by_point[2]
    assert t.eta_by_point[1] < t.eta_by_point[3]


def test_finish_minus_start_is_total_minutes() -> None:
    t = estimate(flat_5km(), START, 1.3, 10.0)
    assert abs((t.finish - t.start) - timedelta(minutes=t.total_min)) <= ONE_MICROSECOND


def test_a_point_after_60_moving_minutes_is_70_minutes_in_at_rest_10() -> None:
    d60 = 1000.0 * FLAT_SPEED_KMH  # metres walked in 60 min on the flat
    t = estimate(make_route([0.0, d60, 2 * d60]), START, 1.0, 10.0)
    assert abs(t.eta_by_point[1] - (START + timedelta(minutes=70))) <= ONE_MICROSECOND
    assert abs(t.eta_by_point[2] - (START + timedelta(minutes=140))) <= ONE_MICROSECOND


def test_pace_is_applied_before_rest_to_etas() -> None:
    d60 = 1000.0 * FLAT_SPEED_KMH
    t = estimate(make_route([0.0, d60]), START, 2.0, 10.0)
    assert abs(t.eta_by_point[1] - (START + timedelta(minutes=140))) <= ONE_MICROSECOND


def test_rest_accrues_in_proportion_to_distance_on_the_flat() -> None:
    route = flat_5km(500.0)
    t = estimate(route, START, 1.0, 30.0)
    for point, eta in zip(route.points, t.eta_by_point, strict=True):
        expected = START + timedelta(minutes=t.total_min * point.dist_m / 5000.0)
        assert abs(eta - expected) <= timedelta(microseconds=2)


def test_eta_tzinfo_is_the_start_tzinfo() -> None:
    plus3 = datetime(2026, 6, 1, 6, 0, tzinfo=timezone(timedelta(hours=3)))
    t = estimate(flat_5km(), plus3, 1.0, 10.0)
    assert all(e.utcoffset() == timedelta(hours=3) for e in t.eta_by_point)
    assert t.start.tzinfo is plus3.tzinfo


def test_utc_and_offset_starts_give_the_same_instants() -> None:
    utc = estimate(flat_5km(), START, 1.0, 10.0).eta_by_point
    offset_start = START.astimezone(timezone(timedelta(hours=-7)))
    off = estimate(flat_5km(), offset_start, 1.0, 10.0).eta_by_point
    assert utc == off


# Israel springs forward Friday 2026-03-27: 02:00 local (UTC+2) becomes 03:00.
SWITCH_UTC = datetime(2026, 3, 27, 0, 0, tzinfo=UTC)
LONG_ROUTE = make_route(
    evenly(10000.0, 100.0)
)  # 10 km flat: 119.1 min moving, 139 total


def test_elapsed_time_is_exact_across_a_dst_jump() -> None:
    zone = SwitchingZone(SWITCH_UTC)
    start = datetime(2026, 3, 27, 0, 30, tzinfo=zone)
    assert start.utcoffset() == timedelta(hours=2)
    t = estimate(LONG_ROUTE, start, 1.0, 10.0)
    elapsed = t.finish.astimezone(UTC) - start.astimezone(UTC)
    assert abs(elapsed - timedelta(minutes=t.total_min)) <= ONE_MICROSECOND
    assert t.finish.utcoffset() == timedelta(hours=3)
    # 00:30 + 2 h 18 m 59 s of walking, plus the hour the clock skipped, is 03:48:59
    wall = t.finish.replace(tzinfo=None)
    assert abs(wall - datetime(2026, 3, 27, 3, 48, 59)) < timedelta(seconds=2)


def test_dst_start_and_its_utc_equivalent_give_the_same_instants() -> None:
    zone = SwitchingZone(SWITCH_UTC)
    start = datetime(2026, 3, 27, 0, 30, tzinfo=zone)
    local = estimate(LONG_ROUTE, start, 1.0, 10.0).eta_by_point
    utc = estimate(LONG_ROUTE, start.astimezone(UTC), 1.0, 10.0).eta_by_point
    assert [e.astimezone(UTC) for e in local] == utc


def test_dst_result_keeps_the_start_tzinfo() -> None:
    zone = SwitchingZone(SWITCH_UTC)
    start = datetime(2026, 3, 27, 0, 30, tzinfo=zone)
    t = estimate(LONG_ROUTE, start, 1.0, 10.0)
    assert all(e.tzinfo is zone for e in t.eta_by_point)
