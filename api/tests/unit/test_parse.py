"""Unit tests for app.routes.parse and app.routes.xml_guard."""

import pytest

from app.routes.errors import InvalidGpx
from app.routes.parse import drop_consecutive_duplicates, parse_gpx
from app.routes.track import RawPoint
from app.routes.xml_guard import check_gpx_prolog


def p(lat: float, lon: float, ele: float | None = None) -> RawPoint:
    return RawPoint(lat, lon, ele)


# --- drop_consecutive_duplicates ---------------------------------------------------


def test_the_first_of_a_run_is_kept_with_its_elevation() -> None:
    out = drop_consecutive_duplicates([p(1, 1, 5.0), p(1, 1, 9.0), p(2, 2, 1.0)])
    assert out == (p(1, 1, 5.0), p(2, 2, 1.0))


def test_duplicates_are_dropped_across_what_were_segment_boundaries() -> None:
    merged = [p(1, 1), p(2, 2), p(2, 2), p(3, 3)]
    assert drop_consecutive_duplicates(merged) == (p(1, 1), p(2, 2), p(3, 3))


def test_non_consecutive_repeats_and_near_duplicates_stay() -> None:
    pts = [p(1, 1), p(2, 2), p(1, 1), p(1, 1.0000001)]
    assert drop_consecutive_duplicates(pts) == tuple(pts)


def test_dedupe_of_nothing_is_nothing() -> None:
    assert drop_consecutive_duplicates([]) == ()


# --- parse_gpx -----------------------------------------------------------------------

TRK = (
    '<gpx version="1.1" creator="t"><trk><name>T</name><trkseg>'
    '<trkpt lat="1" lon="1"><ele>5</ele></trkpt><trkpt lat="2" lon="2"/>'
    "</trkseg></trk>{extra}</gpx>"
)
RTE = '<rte><name>R</name><rtept lat="3" lon="3"/><rtept lat="4" lon="4"/></rte>'


def test_trk_is_preferred_and_names_are_reported() -> None:
    raw = parse_gpx(TRK.format(extra=RTE).encode())
    assert raw.source_format == "trk"
    assert raw.points == (p(1, 1, 5.0), p(2, 2, None))
    assert raw.track_name == "T"
    assert raw.metadata_name is None


def test_rte_is_the_fallback_and_its_name_is_used() -> None:
    data = '<gpx version="1.1" creator="t">' + RTE + "</gpx>"
    raw = parse_gpx(data.encode())
    assert raw.source_format == "rte"
    assert raw.track_name == "R"
    assert raw.points == (p(3, 3), p(4, 4))


def test_the_source_with_more_points_wins_when_neither_has_two() -> None:
    data = (
        '<gpx version="1.1" creator="t"><trk><trkseg><trkpt lat="1" lon="1"/>'
        '</trkseg></trk><rte><rtept lat="2" lon="2"/></rte></gpx>'
    )
    assert parse_gpx(data.encode()).source_format == "trk"
    more_rte = (
        '<gpx version="1.1" creator="t"><trk/><rte><rtept lat="2" lon="2"/></rte></gpx>'
    )
    assert parse_gpx(more_rte.encode()).source_format == "rte"
    nothing = parse_gpx(b'<gpx version="1.1" creator="t"/>')
    assert nothing.points == () and nothing.source_format == "trk"


def test_metadata_name_is_read() -> None:
    data = '<gpx version="1.1" creator="t"><metadata><name>Meta</name></metadata></gpx>'
    assert parse_gpx(data.encode()).metadata_name == "Meta"


def test_non_finite_ele_becomes_none() -> None:
    data = (
        '<gpx version="1.1" creator="t"><trk><trkseg>'
        '<trkpt lat="1" lon="1"><ele>nan</ele></trkpt>'
        '<trkpt lat="2" lon="2"><ele>inf</ele></trkpt></trkseg></trk></gpx>'
    )
    assert [q.elev_m for q in parse_gpx(data.encode()).points] == [None, None]


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\xff\xfe",
        b"<gpx",
        b'<gpx><trk><trkseg><trkpt lat="1"/></trkseg></trk></gpx>',
    ],
)
def test_bad_input_is_invalid_gpx(data: bytes) -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(data)


def test_a_gpxpy_failure_is_wrapped_as_invalid_gpx() -> None:
    data = b'<gpx><trk><trkseg><trkpt lat="x" lon="1"/></trkseg></trk></gpx>'
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(data)
    assert excinfo.value.__cause__ is not None


# --- check_gpx_prolog ----------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        b"<gpx/>",
        b'<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"/>',
        b'<gpx version="1.0" xmlns="http://www.topografix.com/GPX/1/0"/>',
        b'\xef\xbb\xbf<?xml version="1.0"?><!-- c --><gpx/>',
        b'<g:gpx xmlns:g="http://www.topografix.com/GPX/1/1"/>',
    ],
)
def test_gpx_roots_pass(data: bytes) -> None:
    check_gpx_prolog(data)


@pytest.mark.parametrize(
    "data",
    [
        b"<kml/>",
        b"<GPX/>",
        b"<a><gpx/></a>",
        b"",
        b"   ",
        b"<!-- only a comment -->",
        b"not xml",
        b'<!DOCTYPE gpx [<!ENTITY a "b">]><gpx/>',
        b"<!DOCTYPE gpx><gpx/>",
        b'<!DOCTYPE gpx SYSTEM "http://127.0.0.1:9/x.dtd"><gpx/>',
    ],
)
def test_other_documents_are_rejected(data: bytes) -> None:
    with pytest.raises(InvalidGpx):
        check_gpx_prolog(data)


def test_malformed_prolog_reports_the_position() -> None:
    with pytest.raises(InvalidGpx, match=r"line 1, column"):
        check_gpx_prolog(b"<?xml version='1.0'?><<gpx/>")


def test_the_guard_stops_at_the_root_and_ignores_a_broken_body() -> None:
    check_gpx_prolog(b"<gpx><trk><<<<<")


# --- implausible elevations and unsupported encodings ------------------------------


def _ele_doc(ele: str) -> bytes:
    return (
        f'<gpx><trk><trkseg><trkpt lat="1" lon="1"><ele>{ele}</ele></trkpt>'
        '<trkpt lat="1.001" lon="1"/></trkseg></trk></gpx>'
    ).encode()


@pytest.mark.parametrize(
    ("ele", "expected"),
    [
        ("-1000", -1000.0),
        ("10000", 10000.0),
        ("-1000.0001", None),
        ("10000.0001", None),
        ("1e308", None),
        ("-1e308", None),
        ("nan", None),
        ("inf", None),
        ("0", 0.0),
    ],
)
def test_elevation_bounds_are_inclusive_and_outside_becomes_none(
    ele: str, expected: float | None
) -> None:
    assert parse_gpx(_ele_doc(ele)).points[0].elev_m == expected


@pytest.mark.parametrize(
    "encoding", ["utf-32", "utf-7", "x-mac-hebrew", "", "nope", "shift_jis", "big5"]
)
def test_unsupported_xml_encoding_is_invalid_gpx(encoding: str) -> None:
    data = f'<?xml version="1.0" encoding="{encoding}"?><gpx/>'.encode()
    with pytest.raises(InvalidGpx, match="encoding|well-formed"):
        check_gpx_prolog(data)
