"""Behaviour of summarise_gpx on small synthetic tracks (no fixtures)."""

import unicodedata
from typing import Literal

import pytest

from app.routes.errors import InvalidGpx, TooFewPoints
from app.routes.params import ParseParams
from app.routes.summary import summarise_gpx
from tests.routes.gpx_builders import (
    Pt,
    add_rte,
    destination,
    gpx_bytes,
    haversine_m,
    out_and_back,
    path_length_m,
    straight_line,
)

A = Pt(31.9, 34.9, 100.0)


# --- source selection, merging, duplicates --------------------------------------


def test_trk_is_preferred_over_rte_when_both_have_two_points() -> None:
    data = add_rte(gpx_bytes([straight_line(3)]), straight_line(5, step_m=50.0))
    result = summarise_gpx(data, None)
    assert result.source_format == "trk"
    assert result.point_count_original == 3


def test_rte_is_used_when_the_trk_has_fewer_than_two_points() -> None:
    data = add_rte(gpx_bytes([straight_line(1)]), straight_line(4))
    result = summarise_gpx(data, None)
    assert result.source_format == "rte"
    assert result.point_count_original == 4


def test_tracks_and_segments_are_merged_in_document_order() -> None:
    one = straight_line(3, start=A)
    two = straight_line(3, start=destination(A, 90.0, 5000.0))
    three = straight_line(2, start=destination(A, 180.0, 5000.0))
    data = gpx_bytes([one, two, three], track_names=["a", "b", "c"])
    result = summarise_gpx(data, None)
    merged = [*one, *two, *three]
    assert result.point_count_original == 8
    assert result.distance_m == pytest.approx(path_length_m(merged), rel=1e-9)
    assert (result.start.lat, result.start.lon) == (one[0].lat, one[0].lon)
    assert (result.end.lat, result.end.lon) == (three[-1].lat, three[-1].lon)


def test_distance_counts_the_jump_between_segments() -> None:
    first = straight_line(5, start=A, bearing_deg=0.0)
    second = straight_line(5, start=destination(A, 90.0, 3000.0), bearing_deg=0.0)
    result = summarise_gpx(gpx_bytes([first, second]), None)
    jump = haversine_m(first[-1], second[0])
    assert jump > 1000
    expected = path_length_m(first) + jump + path_length_m(second)
    assert result.distance_m == pytest.approx(expected, rel=1e-9)
    dists = [p.dist_m for p in result.points]
    assert dists == sorted(dists)
    assert dists[-1] == pytest.approx(expected, rel=1e-9)


def test_consecutive_duplicates_are_dropped_but_counted_in_the_original() -> None:
    pts = straight_line(4)
    with_dupes = [pts[0], pts[0], pts[1], pts[2], pts[2], pts[2], pts[3]]
    result = summarise_gpx(gpx_bytes([with_dupes]), None)
    assert result.point_count_original == 7
    assert len(result.points) == 4
    assert result.distance_m == pytest.approx(path_length_m(pts), rel=1e-9)


def test_duplicates_across_a_segment_boundary_are_dropped() -> None:
    pts = straight_line(6)
    result = summarise_gpx(gpx_bytes([pts[:3], pts[2:]]), None)
    assert len(result.points) == 6
    assert result.distance_m == pytest.approx(path_length_m(pts), rel=1e-9)


def test_non_consecutive_repeats_are_kept() -> None:
    a, b = straight_line(2)
    result = summarise_gpx(gpx_bytes([[a, b, a]]), None)
    assert len(result.points) == 3
    assert result.distance_m == pytest.approx(2 * haversine_m(a, b), rel=1e-9)


def test_the_first_of_two_duplicate_points_keeps_its_elevation() -> None:
    a, b = straight_line(2, ele=10.0)
    result = summarise_gpx(gpx_bytes([[a, Pt(a.lat, a.lon, 999.0), b]]), None)
    assert result.max_elev_m == 10.0
    assert result.start.elev_m == 10.0


# --- too few points ---------------------------------------------------------------


def test_single_point_track_is_too_few_points() -> None:
    with pytest.raises(TooFewPoints):
        summarise_gpx(gpx_bytes([straight_line(1)]), None)


def test_two_identical_points_are_too_few_points() -> None:
    p = straight_line(1)[0]
    with pytest.raises(TooFewPoints):
        summarise_gpx(gpx_bytes([[p, p]]), None)


def test_all_duplicate_points_are_too_few_points() -> None:
    p = straight_line(1)[0]
    with pytest.raises(TooFewPoints):
        summarise_gpx(gpx_bytes([[p] * 50]), None)


def test_gpx_with_no_tracks_is_too_few_points() -> None:
    with pytest.raises(TooFewPoints):
        summarise_gpx(b'<gpx version="1.1" creator="t"></gpx>', None)


def test_waypoint_only_file_is_too_few_points() -> None:
    wpts = "".join(f'<wpt lat="31.9{i}" lon="34.9{i}"/>' for i in range(5))
    data = f'<gpx version="1.1" creator="t">{wpts}</gpx>'.encode()
    with pytest.raises(TooFewPoints):
        summarise_gpx(data, None)


def test_one_trk_point_plus_one_rte_point_is_too_few_points() -> None:
    data = (
        b'<gpx version="1.1" creator="t"><trk><trkseg><trkpt lat="1" lon="1"/>'
        b'</trkseg></trk><rte><rtept lat="2" lon="2"/></rte></gpx>'
    )
    with pytest.raises(TooFewPoints):
        summarise_gpx(data, None)


# --- invalid input ---------------------------------------------------------------


def test_empty_input_is_invalid_gpx() -> None:
    with pytest.raises(InvalidGpx):
        summarise_gpx(b"", None)


def test_non_utf8_bytes_are_invalid_gpx() -> None:
    data = gpx_bytes([straight_line(3)], metadata_name="x").replace(b"x", b"\xe9")
    with pytest.raises(InvalidGpx):
        summarise_gpx(data, None)


def test_utf16_encoded_gpx_is_invalid_gpx() -> None:
    data = '<gpx version="1.1"><trk/></gpx>'.encode("utf-16")
    with pytest.raises(InvalidGpx):
        summarise_gpx(data, None)


@pytest.mark.parametrize(
    "root", ["<kml/>", "<html><body/></html>", "<GPX/>", "<gpxx/>", "<a><gpx/></a>"]
)
def test_non_gpx_root_is_invalid_gpx(root: str) -> None:
    with pytest.raises(InvalidGpx):
        summarise_gpx(root.encode(), None)


@pytest.mark.parametrize(
    "attrs",
    [
        'lat="91" lon="10"',
        'lat="-90.0001" lon="10"',
        'lat="10" lon="180.5"',
        'lat="10" lon="-181"',
        'lat="NaN" lon="10"',
        'lat="10" lon="inf"',
        'lat="1e999" lon="10"',
        'lat="x" lon="10"',
        'lon="10"',
        'lat="10"',
    ],
)
def test_bad_coordinates_are_invalid_gpx(attrs: str) -> None:
    data = (
        '<gpx version="1.1" creator="t"><trk><trkseg>'
        '<trkpt lat="10" lon="10"/>'
        f"<trkpt {attrs}/>"
        '<trkpt lat="10.001" lon="10"/>'
        "</trkseg></trk></gpx>"
    ).encode()
    with pytest.raises(InvalidGpx):
        summarise_gpx(data, None)


def test_bad_coordinate_in_the_unchosen_source_does_not_reject_the_file() -> None:
    """Only the chosen source's points are validated (ADR 3.1 step 8)."""
    good = straight_line(3)
    data = gpx_bytes([good]).replace(
        b"</gpx>", b'<rte><rtept lat="95" lon="0"/><rtept lat="0" lon="0"/></rte></gpx>'
    )
    assert summarise_gpx(data, None).source_format == "trk"


def test_pole_to_pole_coordinates_are_accepted() -> None:
    data = gpx_bytes([[Pt(-90.0, -180.0, 0.0), Pt(90.0, 180.0, 5.0)]])
    result = summarise_gpx(data, None)
    assert result.distance_m == pytest.approx(
        path_length_m([Pt(-90, 0, 0), Pt(90, 0, 0)]), rel=1e-6
    )


def test_two_points_at_the_same_pole_with_different_longitudes_do_not_crash() -> None:
    data = gpx_bytes([[Pt(90.0, 0.0, 1.0), Pt(90.0, 90.0, 2.0)]])
    try:
        result = summarise_gpx(data, None)
    except TooFewPoints:
        return
    assert result.distance_m == pytest.approx(0.0, abs=1e-3)
    assert result.gain_m is not None and result.gain_m >= 0


# --- accepted dialects -------------------------------------------------------------


@pytest.mark.parametrize("version", ["1.0", "1.1", "none"])
def test_gpx_1_0_1_1_and_namespace_free_roots_are_accepted(
    version: Literal["1.0", "1.1", "none"],
) -> None:
    pts = straight_line(4)
    data = gpx_bytes([pts], version=version)
    assert summarise_gpx(data, None).distance_m == pytest.approx(
        path_length_m(pts), rel=1e-9
    )


def test_a_utf8_bom_is_accepted() -> None:
    pts = straight_line(4)
    result = summarise_gpx(gpx_bytes([pts], bom=True), None)
    assert result.distance_m == pytest.approx(path_length_m(pts), rel=1e-9)


def test_trailing_whitespace_after_the_root_is_accepted() -> None:
    pts = straight_line(4)
    result = summarise_gpx(gpx_bytes([pts], extra_after_root="\n\n   \n"), None)
    assert result.point_count_original == 4


def test_time_elements_do_not_change_the_result() -> None:
    """Odd UTC offsets and a DST-gap local time are ignored by the pipeline."""
    pts = straight_line(30)
    plain = summarise_gpx(gpx_bytes([pts]), None)
    stamped = summarise_gpx(gpx_bytes([pts], times=True), None)
    assert stamped == plain


# --- elevation presence -------------------------------------------------------------


def test_a_single_missing_ele_means_no_elevation_at_all() -> None:
    pts = straight_line(10, ele=None)
    pts = [Pt(p.lat, p.lon, 100.0 + i) for i, p in enumerate(pts)]
    pts[4] = Pt(pts[4].lat, pts[4].lon, None)
    result = summarise_gpx(gpx_bytes([pts]), None)
    assert result.has_elevation is False
    assert result.elevation_source == "none"
    assert result.gain_m is None and result.loss_m is None
    assert result.min_elev_m is None and result.max_elev_m is None
    assert result.high_point is None
    assert all(p.elev_m is None for p in result.points)
    assert result.start.elev_m is None and result.end.elev_m is None


def test_a_nan_ele_is_treated_as_missing() -> None:
    data = (
        b'<gpx version="1.1" creator="t"><trk><trkseg>'
        b'<trkpt lat="10" lon="10"><ele>5</ele></trkpt>'
        b'<trkpt lat="10.001" lon="10"><ele>nan</ele></trkpt>'
        b'<trkpt lat="10.002" lon="10"><ele>7</ele></trkpt>'
        b"</trkseg></trk></gpx>"
    )
    result = summarise_gpx(data, None)
    assert result.has_elevation is False
    assert result.gain_m is None


def test_flat_route_has_zero_gain_not_null() -> None:
    result = summarise_gpx(gpx_bytes([straight_line(50, ele=250.0)]), None)
    assert result.has_elevation is True
    assert result.gain_m == 0
    assert result.loss_m == 0
    assert result.min_elev_m == result.max_elev_m == 250.0


def test_high_point_is_the_first_of_equal_maxima() -> None:
    pts = straight_line(9, ele=0.0)
    pts[2] = Pt(pts[2].lat, pts[2].lon, 50.0)
    pts[6] = Pt(pts[6].lat, pts[6].lon, 50.0)
    result = summarise_gpx(gpx_bytes([pts]), None)
    assert result.high_point is not None
    assert (result.high_point.lat, result.high_point.lon) == (pts[2].lat, pts[2].lon)


def test_extreme_elevations_are_summarised_without_error() -> None:
    pts = [
        Pt(p.lat, p.lon, e)
        for p, e in zip(
            straight_line(5), [-400.0, 8848.0, -400.0, 8848.0, 0.0], strict=True
        )
    ]
    result = summarise_gpx(gpx_bytes([pts]), None)
    assert result.max_elev_m == 8848.0
    assert result.min_elev_m == -400.0
    assert result.gain_m is not None and result.gain_m >= 0


# --- is_loop ------------------------------------------------------------------------


def test_out_and_back_is_a_loop() -> None:
    assert summarise_gpx(gpx_bytes([out_and_back()]), None).is_loop is True


def test_one_way_route_is_not_a_loop() -> None:
    result = summarise_gpx(gpx_bytes([straight_line(101, step_m=20.0)]), None)
    assert result.distance_m == pytest.approx(2000.0, rel=1e-3)
    assert result.is_loop is False


def _ends_apart(gap_m: float) -> bytes:
    out = straight_line(51, step_m=20.0)  # 1 km north
    return gpx_bytes([[*out, destination(out[0], 0.0, gap_m)]])


def test_loop_boundary_199_m_is_a_loop_and_201_m_is_not() -> None:
    assert summarise_gpx(_ends_apart(199.0), None).is_loop is True
    assert summarise_gpx(_ends_apart(201.0), None).is_loop is False


def test_loop_threshold_parameter_is_honoured() -> None:
    data = _ends_apart(100.0)
    assert summarise_gpx(data, None, ParseParams()).is_loop is True
    assert (
        summarise_gpx(data, None, ParseParams(loop_threshold_m=50.0)).is_loop is False
    )


# --- simplification through the pipeline --------------------------------------------


def test_track_of_at_most_500_points_is_returned_unchanged() -> None:
    pts = straight_line(500, step_m=3.0)
    result = summarise_gpx(gpx_bytes([pts]), None)
    assert [(p.lat, p.lon) for p in result.points] == [(p.lat, p.lon) for p in pts]


def test_501_points_are_cut_to_exactly_500() -> None:
    result = summarise_gpx(gpx_bytes([straight_line(501, step_m=3.0)]), None)
    assert len(result.points) == 500


def test_max_points_parameter_is_honoured() -> None:
    result = summarise_gpx(
        gpx_bytes([straight_line(100)]), None, ParseParams(max_points=10)
    )
    assert len(result.points) == 10


def test_simplify_keeps_start_end_and_high_point_on_a_straight_line() -> None:
    """RDP on a straight line has no reason to keep the high point; we must."""
    pts = straight_line(2000, step_m=5.0, ele=100.0)
    spike = 1234
    pts[spike] = Pt(pts[spike].lat, pts[spike].lon, 900.0)
    result = summarise_gpx(gpx_bytes([pts]), None)
    assert len(result.points) == 500
    assert (result.points[0].lat, result.points[0].lon) == (pts[0].lat, pts[0].lon)
    assert (result.points[-1].lat, result.points[-1].lon) == (pts[-1].lat, pts[-1].lon)
    assert result.high_point is not None
    assert (result.high_point.lat, result.high_point.lon) == (
        pts[spike].lat,
        pts[spike].lon,
    )
    assert any(
        (p.lat, p.lon) == (pts[spike].lat, pts[spike].lon) for p in result.points
    )
    assert max(p.elev_m for p in result.points if p.elev_m is not None) == 900.0


def test_simplify_keeps_a_loops_start_and_end_when_they_coincide() -> None:
    out = straight_line(300, step_m=10.0)
    loop = [*out, *(destination(p, 90.0, 400.0) for p in reversed(out)), out[0]]
    result = summarise_gpx(gpx_bytes([loop]), None)
    assert len(result.points) == 500
    assert result.is_loop is True
    assert (result.points[0].lat, result.points[0].lon) == (out[0].lat, out[0].lon)
    assert (result.points[-1].lat, result.points[-1].lon) == (out[0].lat, out[0].lon)


def test_a_deep_track_does_not_hit_the_recursion_limit() -> None:
    result = summarise_gpx(gpx_bytes([straight_line(5000, step_m=2.0)]), None)
    assert len(result.points) == 500


# --- name -------------------------------------------------------------------------


def _named(
    *, meta: str | None = None, trk: str | None = None, filename: str | None = None
) -> str:
    data = gpx_bytes(
        [straight_line(3)],
        metadata_name=meta,
        track_names=[trk] if trk is not None else (),
    )
    return summarise_gpx(data, filename).name


def test_metadata_name_beats_track_name_and_filename() -> None:
    assert _named(meta="Meta", trk="Track", filename="file.gpx") == "Meta"


def test_track_name_beats_filename() -> None:
    assert _named(trk="Track", filename="file.gpx") == "Track"


def test_filename_stem_replaces_underscores_and_drops_the_extension() -> None:
    assert _named(filename="My_Hike.gpx") == "My Hike"


@pytest.mark.parametrize(
    ("filename", "name"),
    [
        ("C:\\x\\My_Hike.GPX", "My Hike"),
        ("/home/u/My_Hike.gpx", "My Hike"),
        ("..\\..\\up\\Evening_walk.gpx", "Evening walk"),
        ("archive.tar.gpx", "archive.tar"),
        ("no_extension", "no extension"),
        (
            "\u05ea\u05dc_\u05d7\u05d3\u05d9\u05d3.gpx",
            "\u05ea\u05dc \u05d7\u05d3\u05d9\u05d3",
        ),
    ],
)
def test_filename_normalisation(filename: str, name: str) -> None:
    assert _named(filename=filename) == name


@pytest.mark.parametrize("filename", [None, "", ".gpx", "   .gpx", "/", "dir/"])
def test_untitled_route_when_nothing_gives_a_name(filename: str | None) -> None:
    assert _named(filename=filename) == "Untitled route"


def test_whitespace_only_metadata_and_track_names_are_skipped() -> None:
    assert (
        _named(meta="   ", trk=" \u00a0 ", filename="Fallback_name.gpx")
        == "Fallback name"
    )
    assert _named(meta="   ", trk="Track") == "Track"


def test_first_non_blank_track_name_is_used() -> None:
    data = gpx_bytes(
        [straight_line(3), straight_line(3, bearing_deg=90.0)],
        track_names=[" ", "Second"],
    )
    assert summarise_gpx(data, None).name == "Second"


def test_rte_name_is_used_for_an_rte_source() -> None:
    data = gpx_bytes([straight_line(3)], kind="rte", track_names=["Route name"])
    assert summarise_gpx(data, "f.gpx").name == "Route name"


def test_name_whitespace_runs_collapse_and_ends_are_trimmed() -> None:
    assert _named(meta="  A   B \u00a0 C  ") == "A B C"


def test_control_characters_are_stripped_from_every_candidate() -> None:
    assert not any(
        unicodedata.category(c) == "Cc" for c in _named(meta="A\u0085B\u009fC")
    )
    result = _named(filename="bad\x07na\x00me.gpx")
    assert result == "badname"


def test_name_is_cut_to_200_code_points() -> None:
    assert len(_named(meta="x" * 300)) == 200
    assert len(_named(filename="y" * 500 + ".gpx")) == 200
    emoji = _named(meta="\U0001f600" * 250)
    assert emoji == "\U0001f600" * 200


def test_hebrew_names_are_kept() -> None:
    assert (
        _named(meta="\u05d1\u05df \u05e9\u05de\u05df")
        == "\u05d1\u05df \u05e9\u05de\u05df"
    )
