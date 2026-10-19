"""Tracks of 501-2,500 points: simplify and pre-thinning through the whole pipeline.

``tracks()`` stops at 200 points, so before this file no property reached ``simplify``
(more than 500 points) or the 2,000-point pre-thinning threshold (ADR 0004 3.5).
"""

import pytest
from hypothesis import HealthCheck, given, settings

from app.models.route import RouteSummary
from app.routes.summary import summarise_gpx
from tests.routes.strategies import LongShape, Track, long_track, long_tracks


def check(track: Track, summary: RouteSummary) -> None:
    flat = track.flat
    assert summary.point_count_original == len(flat)
    assert len(summary.points) == 500
    first, last = summary.points[0], summary.points[-1]
    assert (first.lat, first.lon) == (flat[0].lat, flat[0].lon)
    assert (last.lat, last.lon) == (flat[-1].lat, flat[-1].lon)
    assert (first.lat, first.lon) == (summary.start.lat, summary.start.lon)
    assert (last.lat, last.lon) == (summary.end.lat, summary.end.lon)
    assert first.dist_m == 0.0
    assert last.dist_m == summary.distance_m
    dists = [p.dist_m for p in summary.points]
    assert dists == sorted(dists)
    assert len(set((p.lat, p.lon) for p in summary.points)) == 500  # distinct points
    if track.elevation == "none":
        assert summary.high_point is None
        return
    elevations = [p.ele for p in flat]
    top = max(e for e in elevations if e is not None)
    high = flat[elevations.index(top)]  # the first maximum
    assert summary.max_elev_m == top
    assert summary.high_point is not None
    assert (summary.high_point.lat, summary.high_point.lon) == (high.lat, high.lon)
    kept = {(p.lat, p.lon, p.elev_m) for p in summary.points}
    assert (high.lat, high.lon, top) in kept
    assert max(p.elev_m for p in summary.points if p.elev_m is not None) == top


@settings(
    max_examples=20,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(long_tracks())
def test_long_tracks_give_exactly_500_points_keeping_start_end_and_high_point(
    track: Track,
) -> None:
    check(track, summarise_gpx(track.gpx(), "t.gpx"))


@pytest.mark.parametrize("n", [501, 1999, 2000, 2001, 2500])
@pytest.mark.parametrize("shape", ["walk", "zigzag", "line"])
def test_the_thinning_threshold_neighbourhood_gives_the_same_guarantees(
    n: int, shape: LongShape
) -> None:
    track = long_track(n, seed=n, shape=shape)
    check(track, summarise_gpx(track.gpx(), "t.gpx"))


def test_the_strategy_builds_distinct_points_and_is_reproducible() -> None:
    a, b = long_track(700, 5, "walk"), long_track(700, 5, "walk")
    assert a == b
    assert len({(p.lat, p.lon) for p in a.flat}) == 700
    assert long_track(700, 6, "walk") != a
