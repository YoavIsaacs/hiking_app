"""Hypothesis properties of the pipeline and of the pure elevation functions."""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.route import RouteSummary
from app.routes.elevation import gain_loss, smooth_elevation
from app.routes.errors import TooFewPoints
from app.routes.summary import summarise_gpx
from tests.routes.gpx_builders import dedupe, path_length_m
from tests.routes.strategies import Track, tracks

PIPELINE = settings(deadline=None, max_examples=60, derandomize=True)

finite = st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False)


def run(track: Track) -> RouteSummary | None:
    try:
        return summarise_gpx(track.gpx(), "t.gpx")
    except TooFewPoints:
        return None


@PIPELINE
@given(tracks())
def test_random_tracks_have_non_negative_distance_gain_and_loss(track: Track) -> None:
    result = run(track)
    if result is None:
        return
    assert result.distance_m >= 0
    if track.elevation == "all":
        assert result.has_elevation is True
    if track.elevation == "none":
        assert result.has_elevation is False
    if result.has_elevation:
        assert result.gain_m is not None and result.gain_m >= 0
        assert result.loss_m is not None and result.loss_m >= 0
    else:
        assert result.gain_m is None and result.loss_m is None


@PIPELINE
@given(tracks())
def test_reversed_track_has_the_same_distance_and_swapped_gain_and_loss(
    track: Track,
) -> None:
    forward, backward = run(track), run(track.reversed())
    assert (forward is None) == (backward is None)
    if forward is None or backward is None:
        return
    assert backward.distance_m == pytest.approx(forward.distance_m, rel=1e-9, abs=1e-9)
    if forward.gain_m is None:
        assert backward.gain_m is None and backward.loss_m is None
        return
    assert forward.loss_m is not None and backward.gain_m is not None
    assert backward.gain_m == pytest.approx(forward.loss_m, abs=1e-6)
    assert backward.loss_m == pytest.approx(forward.gain_m, abs=1e-6)


@PIPELINE
@given(tracks())
def test_random_track_summary_invariants(track: Track) -> None:
    result = run(track)
    kept = dedupe(track.flat)
    if result is None:
        assert len(kept) < 2
        return
    assert result.point_count_original == len(track.flat)
    assert result.distance_m == pytest.approx(path_length_m(kept), rel=1e-9, abs=1e-9)
    assert len(result.points) == min(len(kept), 500)
    dists = [p.dist_m for p in result.points]
    assert dists[0] == 0
    assert dists == sorted(dists)
    assert dists[-1] == pytest.approx(result.distance_m, rel=1e-9, abs=1e-9)
    assert result.source_format == track.kind
    if result.has_elevation:
        top = max(p.ele for p in kept if p.ele is not None)
        assert result.max_elev_m == top
        assert any(p.elev_m == top for p in result.points)


@PIPELINE
@given(tracks())
def test_summarise_either_returns_or_raises_too_few_points(track: Track) -> None:
    # run() lets every exception other than TooFewPoints escape and fail the test.
    run(track)


# --- exact reversal symmetry of the pure functions ------------------------------------


@settings(max_examples=300, deadline=None, derandomize=True)
@given(
    st.lists(finite, min_size=1, max_size=120),
    st.floats(0.0, 50.0, allow_nan=False),
)
def test_gain_loss_of_the_reversed_series_is_exactly_swapped(
    series: list[float], threshold: float
) -> None:
    gain, loss = gain_loss(series, threshold_m=threshold)
    r_gain, r_loss = gain_loss(list(reversed(series)), threshold_m=threshold)
    assert (r_gain, r_loss) == (loss, gain)
    assert gain >= 0 and loss >= 0


@settings(max_examples=200, deadline=None, derandomize=True)
@given(
    st.lists(finite, min_size=2, max_size=120),
    st.floats(0.0, 50.0, allow_nan=False),
)
def test_gain_minus_loss_telescopes_to_last_minus_first(
    series: list[float], threshold: float
) -> None:
    gain, loss = gain_loss(series, threshold_m=threshold)
    assert gain - loss == pytest.approx(series[-1] - series[0], abs=1e-6)


@settings(max_examples=100, deadline=None, derandomize=True)
@given(
    st.lists(st.floats(1.0, 80.0), min_size=2, max_size=60),
    st.lists(finite, min_size=2, max_size=60),
)
def test_smoothed_gain_minus_loss_telescopes_to_the_smoothed_ends(
    gaps: list[float], elevations: list[float]
) -> None:
    n = min(len(gaps), len(elevations))
    dist = [0.0]
    for g in gaps[: n - 1]:
        dist.append(dist[-1] + g)
    smoothed = smooth_elevation(dist, elevations[:n])
    assert smoothed[0] == pytest.approx(elevations[0], abs=1e-9)
    assert smoothed[-1] == pytest.approx(elevations[n - 1], abs=1e-9)
    assert all(math.isfinite(v) for v in smoothed)
    gain, loss = gain_loss(smoothed)
    assert gain - loss == pytest.approx(smoothed[-1] - smoothed[0], abs=1e-6)
