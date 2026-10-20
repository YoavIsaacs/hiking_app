"""Checkpoint measurement: distance within 2 %, gain within 10 % of the reference
on every valid fixture, plus the summary invariants (ADR 0004, "How it is tested")."""

import math
from pathlib import Path

import pytest

from app.models.route import RouteSummary
from app.routes.errors import RouteParseError
from app.routes.summary import summarise_gpx
from tests.fixtures.loader import (
    GPX_DIR,
    Expected,
    edge_case_fixtures,
    fixture_params,
    invalid_fixtures,
    valid_fixtures,
)
from tests.routes.fixture_oracle import metadata_name, read_points
from tests.routes.gpx_builders import dedupe, haversine_m

VALID = fixture_params(valid_fixtures())
WITH_ELEVATION = fixture_params([f for f in valid_fixtures() if f[1].has_elevation])
WITHOUT_ELEVATION = fixture_params(
    [f for f in valid_fixtures() if f[1].has_elevation is False]
)
TRK_ONLY = fixture_params([f for f in valid_fixtures() if "rte" not in f[1].edge_cases])


def summarise(path: Path) -> RouteSummary:
    return summarise_gpx(path.read_bytes(), path.name)


@pytest.mark.parametrize(("path", "expected"), VALID)
def test_distance_within_2_percent_of_reference(path: Path, expected: Expected) -> None:
    assert expected.reference_distance_m is not None
    result = summarise(path)
    error = (
        abs(result.distance_m - expected.reference_distance_m)
        / expected.reference_distance_m
    )
    assert error <= 0.02, (
        f"{path.name}: {result.distance_m:.1f} m vs "
        f"{expected.reference_distance_m} m ({error:.2%})"
    )


@pytest.mark.parametrize(("path", "expected"), WITH_ELEVATION)
def test_gain_within_10_percent_of_reference(path: Path, expected: Expected) -> None:
    assert expected.reference_gain_m is not None
    result = summarise(path)
    assert result.gain_m is not None
    error = abs(result.gain_m - expected.reference_gain_m) / expected.reference_gain_m
    assert error <= 0.10, (
        f"{path.name}: {result.gain_m:.1f} m vs "
        f"{expected.reference_gain_m} m ({error:.2%})"
    )


@pytest.mark.parametrize(("path", "expected"), VALID)
def test_fixture_flags_match_expected_json(path: Path, expected: Expected) -> None:
    result = summarise(path)
    assert result.has_elevation == expected.has_elevation
    assert result.is_loop == expected.is_loop


@pytest.mark.parametrize(("path", "expected"), fixture_params(invalid_fixtures()))
def test_invalid_fixtures_raise_the_expected_error_code(
    path: Path, expected: Expected
) -> None:
    with pytest.raises(RouteParseError) as excinfo:
        summarise(path)
    assert excinfo.value.code == expected.expected_error


@pytest.mark.parametrize(("path", "expected"), VALID)
def test_points_are_capped_and_include_start_and_end(
    path: Path, expected: Expected
) -> None:
    result = summarise(path)
    assert 2 <= len(result.points) <= 500
    first, last = result.points[0], result.points[-1]
    assert (first.lat, first.lon, first.elev_m) == (
        result.start.lat,
        result.start.lon,
        result.start.elev_m,
    )
    assert (last.lat, last.lon, last.elev_m) == (
        result.end.lat,
        result.end.lon,
        result.end.elev_m,
    )


@pytest.mark.parametrize(("path", "expected"), VALID)
def test_dist_m_is_cumulative_from_zero_to_distance(
    path: Path, expected: Expected
) -> None:
    result = summarise(path)
    dists = [p.dist_m for p in result.points]
    assert dists[0] == 0
    assert all(b >= a for a, b in zip(dists, dists[1:], strict=False))
    assert dists[-1] == pytest.approx(result.distance_m, rel=1e-9)


@pytest.mark.parametrize(("path", "expected"), VALID)
def test_distance_and_dist_m_match_an_independent_haversine(
    path: Path, expected: Expected
) -> None:
    raw = dedupe(read_points(path))
    cumulative = [0.0]
    for a, b in zip(raw, raw[1:], strict=False):
        cumulative.append(cumulative[-1] + haversine_m(a, b))
    result = summarise(path)
    assert result.distance_m == pytest.approx(cumulative[-1], rel=1e-9)
    by_position: dict[tuple[float, float], list[float]] = {}
    for p, d in zip(raw, cumulative, strict=True):
        by_position.setdefault((p.lat, p.lon), []).append(d)
    for tp in result.points:
        candidates = by_position[(tp.lat, tp.lon)]
        assert any(abs(c - tp.dist_m) < 1e-6 for c in candidates), (
            "dist_m is the distance along the full-resolution track"
        )


@pytest.mark.parametrize(("path", "expected"), VALID)
def test_point_count_original_counts_every_source_point(
    path: Path, expected: Expected
) -> None:
    assert summarise(path).point_count_original == len(read_points(path))


@pytest.mark.parametrize(("path", "expected"), WITH_ELEVATION)
def test_raw_elevation_extremes_and_high_point(path: Path, expected: Expected) -> None:
    raw = dedupe(read_points(path))
    elevations = [p.ele for p in raw if p.ele is not None]
    top = max(elevations)
    first_top = next(p for p in raw if p.ele == top)
    result = summarise(path)
    assert result.has_elevation is True
    assert result.elevation_source == "file"
    assert result.max_elev_m == top
    assert result.min_elev_m == min(elevations)
    assert result.high_point is not None
    assert (result.high_point.lat, result.high_point.lon, result.high_point.elev_m) == (
        first_top.lat,
        first_top.lon,
        top,
    )
    assert any(
        (p.lat, p.lon, p.elev_m) == (first_top.lat, first_top.lon, top)
        for p in result.points
    ), "the high point must survive simplification"
    assert (
        max(p.elev_m for p in result.points if p.elev_m is not None)
        == result.max_elev_m
    )
    assert result.gain_m is not None and result.gain_m >= 0
    assert result.loss_m is not None and result.loss_m >= 0


@pytest.mark.parametrize(("path", "expected"), WITHOUT_ELEVATION)
def test_no_elevation_fixture_reports_null_not_zero(
    path: Path, expected: Expected
) -> None:
    result = summarise(path)
    assert result.has_elevation is False
    assert result.elevation_source == "none"
    assert result.gain_m is None
    assert result.loss_m is None
    assert result.min_elev_m is None
    assert result.max_elev_m is None
    assert result.high_point is None
    assert result.start.elev_m is None
    assert result.end.elev_m is None
    assert all(p.elev_m is None for p in result.points)


@pytest.mark.parametrize(
    ("path", "expected"), fixture_params(edge_case_fixtures("rte"))
)
def test_rte_fixture_parses_with_source_format_rte(
    path: Path, expected: Expected
) -> None:
    result = summarise(path)
    assert result.source_format == "rte"
    assert result.distance_m > 0


@pytest.mark.parametrize(("path", "expected"), TRK_ONLY)
def test_trk_fixtures_parse_with_source_format_trk(
    path: Path, expected: Expected
) -> None:
    assert summarise(path).source_format == "trk"


def test_rte_and_trk_versions_of_modiin_agree() -> None:
    trk = summarise(GPX_DIR / "alltrails-modiin-hills-south-double-loop.gpx")
    rte = summarise(GPX_DIR / "derived-modiin-hills-south-rte.gpx")
    assert rte.distance_m == pytest.approx(trk.distance_m, rel=1e-12)
    assert rte.gain_m == pytest.approx(trk.gain_m, abs=1e-9)
    assert rte.points == trk.points


def test_multi_segment_fixture_distance_includes_the_jump_between_segments() -> None:
    """ADR 0004 3.2: jumps are counted, so the dropped ~34 m path is replaced by
    a 33.8 m straight jump and the distance is within 5 m of the parent."""
    parent = summarise(GPX_DIR / "alltrails-tel-hadid-loop.gpx")
    multi = summarise(GPX_DIR / "derived-tel-hadid-multi-segment.gpx")
    assert abs(parent.distance_m - multi.distance_m) < 5.0
    assert multi.point_count_original == 797


def test_over_10k_fixture_gain_is_density_independent() -> None:
    """The 14x linear densification lies on the same profile as its parent."""
    parent = summarise(GPX_DIR / "alltrails-ben-shemen-hertzl-singletrack.gpx")
    dense = summarise(GPX_DIR / "derived-ben-shemen-over-10k-points.gpx")
    assert parent.gain_m is not None and dense.gain_m is not None
    assert parent.loss_m is not None and dense.loss_m is not None
    assert dense.gain_m == pytest.approx(parent.gain_m, rel=0.03)
    assert dense.loss_m == pytest.approx(parent.loss_m, rel=0.03)
    assert dense.distance_m == pytest.approx(parent.distance_m, rel=0.002)
    assert dense.point_count_original == 10417


@pytest.mark.parametrize(
    ("path", "expected"), fixture_params(edge_case_fixtures("over_10k_points"))
)
def test_over_10k_fixture_is_capped_to_exactly_500_points(
    path: Path, expected: Expected
) -> None:
    assert len(summarise(path).points) == 500


@pytest.mark.parametrize(
    ("path", "expected"), fixture_params(edge_case_fixtures("loop"))
)
def test_loop_fixtures_are_loops(path: Path, expected: Expected) -> None:
    assert summarise(path).is_loop is True


@pytest.mark.parametrize(("path", "expected"), VALID)
def test_name_comes_from_gpx_metadata_over_the_filename(
    path: Path, expected: Expected
) -> None:
    result = summarise_gpx(path.read_bytes(), "ignored_when_metadata_exists.gpx")
    meta = metadata_name(path)
    if meta is not None:
        assert result.name == meta
    else:
        assert result.name  # falls back to track name / filename, never empty


def test_every_float_in_every_summary_is_finite() -> None:
    for path, _ in valid_fixtures():
        result = summarise(path)
        numbers = [result.distance_m, *(p.dist_m for p in result.points)]
        assert all(math.isfinite(n) for n in numbers)
