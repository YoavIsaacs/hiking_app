"""The pure stages of ADR 0005 section 1: summarise_track, with_looked_up_elevation,
with_warning. No I/O anywhere in this file."""

import math
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.models.route import LatLonElev, RouteSummary
from app.models.warnings import ELEVATION_UNAVAILABLE, ApiWarning
from app.routes.elevation import gain_loss, smooth_elevation
from app.routes.params import DEFAULT_PARAMS, ParseParams
from app.routes.parse import parse_gpx
from app.routes.summary import (
    lookup_point_count,
    summarise_gpx,
    summarise_track,
    with_looked_up_elevation,
    with_warning,
)
from tests.elevation_support import TEL_HADID, pair_of, recorded_table
from tests.fixtures.loader import GPX_DIR, fixture_params, valid_fixtures
from tests.routes.gpx_builders import Pt, gpx_bytes, straight_line

NO_ELE = GPX_DIR / "derived-tel-hadid-no-ele.gpx"


def stage1(
    data: bytes | None = None, params: ParseParams | None = None
) -> RouteSummary:
    return summarise_gpx(data or NO_ELE.read_bytes(), "f.gpx", params or ParseParams())


def recorded(summary: RouteSummary) -> list[float]:
    table = recorded_table(TEL_HADID)
    return [table[pair_of(p.lat, p.lon)] for p in summary.points]


def line_summary(n: int, step_m: float = 135.0) -> RouteSummary:
    return stage1(gpx_bytes([straight_line(n, step_m=step_m, ele=None)]))


# --- the exact warning ---------------------------------------------------------------


def test_the_elevation_unavailable_warning_is_exactly_the_adr_value() -> None:
    assert ELEVATION_UNAVAILABLE.model_dump() == {
        "code": "elevation_unavailable",
        "severity": "warn",
        "message": (
            "Elevation could not be looked up, so gain, loss and the elevation "
            "profile are unavailable."
        ),
    }


def test_api_warning_is_frozen_strict_and_needs_a_message() -> None:
    with pytest.raises(ValidationError):
        ApiWarning(code="elevation_unavailable", severity="warn", message="")
    with pytest.raises(ValidationError):
        ApiWarning(code="made_up", severity="warn", message="m")  # type: ignore[arg-type]  # invalid on purpose
    with pytest.raises(ValidationError):
        ApiWarning(code="elevation_unavailable", severity="loud", message="m")  # type: ignore[arg-type]  # invalid on purpose
    with pytest.raises(ValidationError):
        ELEVATION_UNAVAILABLE.message = "x"  # type: ignore[misc]  # frozen on purpose


# --- summarise_gpx / summarise_track: stage 1 ----------------------------------------


@pytest.mark.parametrize(("path", "expected"), fixture_params(valid_fixtures()))
def test_summarise_gpx_is_summarise_track_of_parse_gpx(
    path: Path, expected: object
) -> None:
    data = path.read_bytes()
    assert summarise_track(parse_gpx(data), path.name) == summarise_gpx(data, path.name)


@pytest.mark.parametrize(("path", "expected"), fixture_params(valid_fixtures()))
def test_pure_stage_one_never_reports_warnings_or_a_lookup(
    path: Path, expected: object
) -> None:
    summary = summarise_gpx(path.read_bytes(), path.name)
    assert summary.warnings == []
    assert summary.elevation_source in {"file", "none"}


def test_the_no_elevation_fixture_is_simplified_to_400_points_not_500() -> None:
    summary = stage1()
    assert summary.elevation_source == "none" and summary.has_elevation is False
    # ADR 0005 Amendment 1: about one point per lookup_spacing_m, never 500
    assert len(summary.points) == lookup_point_count(summary.distance_m, DEFAULT_PARAMS)
    assert summary.warnings == []
    assert summary.point_count_original > 700


@pytest.mark.parametrize(
    ("n", "expected"),
    [(10, 10), (399, 399), (400, 400), (401, 400), (1000, 400), (5000, 400)],
)
def test_a_no_elevation_track_has_at_most_400_points(n: int, expected: int) -> None:
    assert len(line_summary(n, step_m=135.0).points) == expected


@pytest.mark.parametrize(
    ("n", "expected"), [(499, 499), (500, 500), (501, 500), (1000, 500)]
)
def test_a_track_with_elevation_keeps_the_500_point_cap(n: int, expected: int) -> None:
    data = gpx_bytes([straight_line(n, step_m=3.0, ele=100.0)])
    summary = stage1(data)
    assert summary.elevation_source == "file" and len(summary.points) == expected


def test_one_missing_ele_among_many_also_gets_the_400_point_cap() -> None:
    pts = straight_line(900, step_m=135.0, ele=100.0)
    pts[450] = Pt(pts[450].lat, pts[450].lon, None)
    summary = stage1(gpx_bytes([pts]))
    assert summary.elevation_source == "none" and len(summary.points) == 400


def test_lookup_max_points_lowers_the_cap_for_no_elevation_tracks_only() -> None:
    params = ParseParams(lookup_max_points=50)
    assert len(stage1(gpx_bytes([straight_line(300, ele=None)]), params).points) == 50
    with_ele = stage1(gpx_bytes([straight_line(300, ele=100.0)]), params)
    assert len(with_ele.points) == 300


def test_the_effective_cap_is_the_smaller_of_max_points_and_lookup_max_points() -> None:
    params = ParseParams(max_points=30)
    assert len(stage1(gpx_bytes([straight_line(300, ele=None)]), params).points) == 30


def test_stage_one_keeps_start_and_end_of_a_no_elevation_track() -> None:
    pts = straight_line(1200, step_m=3.0, ele=None)
    summary = stage1(gpx_bytes([pts]))
    assert (summary.points[0].lat, summary.points[0].lon) == (pts[0].lat, pts[0].lon)
    assert (summary.points[-1].lat, summary.points[-1].lon) == (
        pts[-1].lat,
        pts[-1].lon,
    )
    assert (
        summary.points[0].dist_m == 0.0
        and summary.points[-1].dist_m == summary.distance_m
    )


# --- with_looked_up_elevation: the section 3 table -------------------------------


def test_the_section_3_table_for_a_looked_up_tel_hadid() -> None:
    before = stage1()
    values = recorded(before)
    after = with_looked_up_elevation(before, values)

    assert after.elevation_source == "lookup" and after.has_elevation is True
    assert after.warnings == []
    assert len(after.points) == len(before.points)
    assert len(after.points) == lookup_point_count(before.distance_m, DEFAULT_PARAMS)
    assert [(p.lat, p.lon, p.dist_m) for p in after.points] == [
        (p.lat, p.lon, p.dist_m) for p in before.points
    ]
    assert [p.elev_m for p in after.points] == values  # as returned, not smoothed
    first, last = after.points[0], after.points[-1]
    assert after.start == LatLonElev(lat=first.lat, lon=first.lon, elev_m=first.elev_m)
    assert after.end == LatLonElev(lat=last.lat, lon=last.lon, elev_m=last.elev_m)
    assert after.min_elev_m == min(values) and after.max_elev_m == max(values)
    top = values.index(max(values))  # the first maximum
    assert after.high_point == LatLonElev(
        lat=after.points[top].lat, lon=after.points[top].lon, elev_m=max(values)
    )
    assert (
        max(p.elev_m for p in after.points if p.elev_m is not None) == after.max_elev_m
    )
    for field in (
        "name",
        "distance_m",
        "is_loop",
        "source_format",
        "point_count_original",
    ):
        assert getattr(after, field) == getattr(before, field), field


def test_gain_and_loss_use_the_lookup_pair_on_the_full_resolution_distances() -> None:
    before = stage1()
    values = recorded(before)
    params = ParseParams()
    after = with_looked_up_elevation(before, values, params)
    smoothed = smooth_elevation(
        [p.dist_m for p in before.points],
        values,
        window_m=params.lookup_smoothing_window_m,
        step_m=params.resample_step_m,
        max_samples=params.max_resample_points,
    )
    gain, loss = gain_loss(smoothed, threshold_m=params.lookup_gain_threshold_m)
    assert after.gain_m == pytest.approx(gain, abs=1e-9)
    assert after.loss_m == pytest.approx(loss, abs=1e-9)
    assert after.gain_m is not None and after.loss_m is not None
    assert after.gain_m - after.loss_m == pytest.approx(
        smoothed[-1] - smoothed[0], abs=1e-6
    )


def test_the_file_pair_does_not_leak_into_looked_up_gain() -> None:
    """Tuning 1.2's pair must never move the lookup answer (ADR 0005 section 3)."""
    before = stage1()
    values = recorded(before)
    baseline = with_looked_up_elevation(before, values)
    moved = with_looked_up_elevation(
        before, values, ParseParams(smoothing_window_m=90.0, gain_threshold_m=40.0)
    )
    assert (moved.gain_m, moved.loss_m) == (baseline.gain_m, baseline.loss_m)


def test_the_lookup_pair_does_move_looked_up_gain() -> None:
    before = stage1()
    values = recorded(before)
    baseline = with_looked_up_elevation(before, values)
    moved = with_looked_up_elevation(
        before,
        values,
        ParseParams(lookup_smoothing_window_m=0.0, lookup_gain_threshold_m=0.0),
    )
    assert moved.gain_m != baseline.gain_m


def test_a_steady_climb_of_100_m_is_100_m_of_gain_and_no_loss() -> None:
    before = line_summary(11)  # 1 km, 11 points
    after = with_looked_up_elevation(before, [10.0 * i for i in range(11)])
    assert after.gain_m == pytest.approx(100.0, abs=0.5)
    assert after.loss_m == pytest.approx(0.0, abs=0.5)
    assert after.min_elev_m == 0.0 and after.max_elev_m == 100.0
    assert after.high_point is not None and after.high_point.elev_m == 100.0
    assert after.high_point.lat == after.points[-1].lat


def test_up_then_down_has_equal_gain_and_loss() -> None:
    values = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0, 80.0, 60.0, 40.0, 20.0, 0.0]
    params = ParseParams(
        lookup_smoothing_window_m=0.0
    )  # smoothing would shave the apex
    after = with_looked_up_elevation(line_summary(11), values, params)
    assert after.gain_m == pytest.approx(100.0, abs=1.5)
    assert after.loss_m == pytest.approx(100.0, abs=1.5)
    assert after.high_point is not None and after.high_point.elev_m == 100.0


def test_a_wiggle_under_the_lookup_threshold_is_not_gain() -> None:
    values = [100.0, 102.0] * 5 + [100.0]  # 2 m, under the picked T of 3 m
    after = with_looked_up_elevation(line_summary(11), values)
    assert after.gain_m == 0.0 and after.loss_m == 0.0


def wiggle(amplitude_m: float) -> list[float]:
    """Five 135 m up-down cycles of the given height, one value per 135 m point."""
    return [100.0, 100.0 + amplitude_m] * 5 + [100.0]


def test_a_wiggle_just_under_the_picked_threshold_is_not_gain() -> None:
    """Smoothing off, so T alone decides: 2.99 m is under the picked 3.0 m."""
    params = ParseParams(lookup_smoothing_window_m=0.0)
    assert params.lookup_gain_threshold_m == 3.0
    after = with_looked_up_elevation(line_summary(11), wiggle(2.99), params)
    assert after.gain_m == 0.0 and after.loss_m == 0.0


def test_a_wiggle_just_over_the_picked_threshold_is_counted() -> None:
    """The other side of the boundary: 3.0 m and 3.1 m cycles all count (5 cycles)."""
    params = ParseParams(lookup_smoothing_window_m=0.0)
    for amplitude in (3.0, 3.1):
        after = with_looked_up_elevation(line_summary(11), wiggle(amplitude), params)
        assert after.gain_m == pytest.approx(5 * amplitude, abs=0.2), amplitude
        assert after.loss_m == pytest.approx(5 * amplitude, abs=0.2), amplitude


def test_with_the_picked_smoothing_a_4_m_wiggle_is_counted_and_a_3_5_m_one_is_not() -> (
    None
):
    """The default window and T together: the smoothed excursion crosses T between."""
    under = with_looked_up_elevation(line_summary(11), wiggle(3.5))
    over = with_looked_up_elevation(line_summary(11), wiggle(4.0))
    assert under.gain_m == 0.0 and under.loss_m == 0.0
    assert over.gain_m is not None and over.gain_m > 2.0
    assert over.loss_m is not None and over.loss_m > 2.0


def test_a_wiggle_over_the_lookup_threshold_counts_whatever_the_file_pair_says() -> (
    None
):
    values = [100.0, 105.0] * 5 + [100.0]
    params = ParseParams(
        lookup_smoothing_window_m=0.0,
        lookup_gain_threshold_m=2.0,
        smoothing_window_m=80.0,
        gain_threshold_m=50.0,
    )
    after = with_looked_up_elevation(line_summary(11), values, params)
    assert after.gain_m == pytest.approx(25.0, abs=1.5)
    assert after.loss_m == pytest.approx(25.0, abs=1.5)


def test_the_high_point_is_the_first_of_equal_maxima() -> None:
    values = [10.0, 50.0, 20.0, 50.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    after = with_looked_up_elevation(line_summary(11), values)
    assert after.high_point is not None
    assert (after.high_point.lat, after.high_point.lon) == (
        after.points[1].lat,
        after.points[1].lon,
    )


def test_a_flat_profile_is_zero_gain_not_null() -> None:
    after = with_looked_up_elevation(line_summary(11), [250.0] * 11)
    assert after.gain_m == 0.0 and after.loss_m == 0.0
    assert after.min_elev_m == after.max_elev_m == 250.0


def test_the_input_summary_is_not_changed() -> None:
    before = stage1()
    snapshot = before.model_copy(deep=True)
    with_looked_up_elevation(before, recorded(before))
    assert before == snapshot


def test_a_tuple_of_elevations_is_accepted_like_a_list() -> None:
    before = line_summary(11)
    values = [float(i) for i in range(11)]
    assert with_looked_up_elevation(before, tuple(values)) == with_looked_up_elevation(
        before, values
    )


@settings(max_examples=60, derandomize=True, deadline=None)
@given(st.lists(st.floats(-1000, 10000, allow_nan=False), min_size=11, max_size=11))
def test_looked_up_invariants_hold_for_any_plausible_profile(
    values: list[float],
) -> None:
    before = line_summary(11)
    after = with_looked_up_elevation(before, values)
    assert after.elevation_source == "lookup" and after.warnings == []
    assert [p.elev_m for p in after.points] == values
    assert after.max_elev_m == max(values) and after.min_elev_m == min(values)
    assert after.high_point is not None and after.high_point.elev_m == max(values)
    assert after.start.elev_m == values[0] and after.end.elev_m == values[-1]
    assert after.gain_m is not None and after.loss_m is not None
    assert math.isfinite(after.gain_m) and math.isfinite(after.loss_m)
    assert after.gain_m >= 0 and after.loss_m >= 0
    RouteSummary.model_validate(after.model_dump())  # and still a valid response


# --- with_looked_up_elevation: preconditions ----------------------------------------


def test_it_refuses_a_summary_that_already_has_file_elevation() -> None:
    with_file = stage1(gpx_bytes([straight_line(11, ele=100.0)]))
    assert with_file.elevation_source == "file"
    with pytest.raises(ValueError, match=r".+"):
        with_looked_up_elevation(with_file, [1.0] * 11)


def test_it_refuses_a_summary_that_is_already_looked_up() -> None:
    once = with_looked_up_elevation(line_summary(11), [1.0] * 11)
    with pytest.raises(ValueError, match=r".+"):
        with_looked_up_elevation(once, [1.0] * 11)


@pytest.mark.parametrize("n", [0, 1, 10, 12, 100])
def test_it_refuses_the_wrong_number_of_elevations(n: int) -> None:
    with pytest.raises(ValueError, match=r".+"):
        with_looked_up_elevation(line_summary(11), [1.0] * n)


@pytest.mark.parametrize(
    "bad",
    [math.nan, math.inf, -math.inf, 10000.001, -1000.001, 1e308, -1e308, 99999.0],
)
@pytest.mark.parametrize("position", [0, 5, 10])
def test_it_refuses_a_non_finite_or_implausible_elevation(
    bad: float, position: int
) -> None:
    values = [100.0] * 11
    values[position] = bad
    with pytest.raises(ValueError, match=r".+"):
        with_looked_up_elevation(line_summary(11), values)


@pytest.mark.parametrize("edge", [-1000.0, 10000.0])
def test_the_plausible_bounds_are_inclusive(edge: float) -> None:
    values = [100.0] * 11
    values[3] = edge
    assert (
        with_looked_up_elevation(line_summary(11), values).elevation_source == "lookup"
    )


# --- with_warning ---------------------------------------------------------------------


def test_with_warning_appends_and_changes_nothing_else() -> None:
    before = stage1()
    after = with_warning(before, ELEVATION_UNAVAILABLE)
    assert after.warnings == [ELEVATION_UNAVAILABLE]
    assert before.warnings == []
    assert after.model_copy(update={"warnings": []}) == before
    assert after.elevation_source == "none" and after.has_elevation is False
    assert all(p.elev_m is None for p in after.points)


def test_with_warning_appends_after_existing_warnings() -> None:
    other = ApiWarning(code="elevation_unavailable", severity="info", message="second")
    twice = with_warning(with_warning(stage1(), ELEVATION_UNAVAILABLE), other)
    assert twice.warnings == [ELEVATION_UNAVAILABLE, other]


def test_a_warned_summary_serialises_the_warning_in_the_contract_shape() -> None:
    body = with_warning(stage1(), ELEVATION_UNAVAILABLE).model_dump(mode="json")
    assert body["warnings"] == [
        {
            "code": "elevation_unavailable",
            "severity": "warn",
            "message": ELEVATION_UNAVAILABLE.message,
        }
    ]
