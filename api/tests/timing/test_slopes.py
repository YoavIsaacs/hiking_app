"""segment_slopes(): centred chord window and clamp (ADR 0006 §2, §3)."""

import pytest

from app.timing.estimate import estimate, segment_slopes
from tests.timing.routes import (
    MIN_PER_M_BOUND,
    START,
    make_route,
    spike_distances,
    spike_route,
)


def slopes(dists: list[float], elevs: list[float | None]) -> list[float]:
    return segment_slopes(make_route(dists, elevs).points)


def test_one_value_per_segment() -> None:
    assert len(slopes([0.0, 10.0, 20.0, 30.0], [0.0, 0.0, 0.0, 0.0])) == 3


def test_route_shorter_than_window_gets_its_end_to_end_slope_on_every_segment() -> None:
    assert slopes([0.0, 20.0, 60.0], [0.0, 30.0, 6.0]) == pytest.approx([0.1, 0.1])


def test_segment_longer_than_window_gets_its_own_slope() -> None:
    assert slopes([0.0, 1000.0, 2000.0], [0.0, 100.0, 100.0]) == pytest.approx(
        [0.1, 0.0]
    )


def test_slope_is_clamped_to_plus_and_minus_half() -> None:
    assert slopes([0.0, 100.0], [0.0, 80.0]) == [0.5]
    assert slopes([0.0, 100.0], [80.0, 0.0]) == [-0.5]


def test_zero_length_segment_has_slope_zero() -> None:
    assert slopes([0.0, 100.0, 100.0, 200.0], [0.0, 50.0, 10.0, 10.0])[1] == 0.0


def test_repeated_distance_takes_the_last_points_elevation() -> None:
    # at d=100 the elevation is 10 (last), not 50 (first): slope 0.1, not 0.5
    assert slopes([0.0, 100.0, 100.0, 200.0], [0.0, 50.0, 10.0, 10.0]) == pytest.approx(
        [0.1, 0.0, 0.0]
    )


def test_gps_spike_changes_exactly_two_segments_by_the_window_chord() -> None:
    dists = spike_distances(True)
    assert all(s == 0.0 for s in segment_slopes(spike_route(False).points))
    changed = {
        (dists[i], dists[i + 1]): s
        for i, s in enumerate(segment_slopes(spike_route(True).points))
        if s != 0.0
    }
    assert changed == pytest.approx(
        {(2450.0, 2460.0): 0.1875, (2550.0, 2560.0): -0.1875}
    )


def test_gps_spike_costs_at_most_a_fifth_of_a_minute() -> None:
    plain = estimate(spike_route(False), START, 1.0, 0.0).moving_min
    spiked = estimate(spike_route(True), START, 1.0, 0.0).moving_min
    assert 0.0 < spiked - plain <= 0.2
    assert spiked - plain == pytest.approx(0.1532, rel=5e-3)


def test_spike_on_a_tiny_route_is_bounded_by_the_clamp() -> None:
    # 2 m step with a 30 m jump inside a 4 m route: an unclamped slope would be 15
    route = make_route([0.0, 2.0, 4.0], [0.0, 30.0, 0.0])
    assert max(abs(s) for s in segment_slopes(route.points)) <= 0.5
    assert estimate(route, START, 1.0, 0.0).moving_min <= MIN_PER_M_BOUND * 4.0


def test_decreasing_distance_raises() -> None:
    with pytest.raises(ValueError):
        slopes([0.0, 100.0, 50.0], [0.0, 0.0, 0.0])


def test_missing_elevation_gives_all_zero_slopes() -> None:
    assert slopes([0.0, 100.0, 200.0], [0.0, None, 50.0]) == [0.0, 0.0]
    assert slopes([0.0, 100.0, 200.0], [None, None, None]) == [0.0, 0.0]
