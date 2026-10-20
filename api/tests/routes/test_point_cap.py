"""The raw point cap (ADR 0004 section 3.12): counted during the one expat pass, which
stops at the 100,001st point.

The cap inside ``parse_gpx`` (``max_points=3`` for the tables, the real 100,000 for the
boundary), what counts and what does not, error precedence in document order, and the
endpoint answer (422 ``too_many_points``).
"""

import pytest
from fastapi.testclient import TestClient

from app.routes.errors import InvalidGpx, RouteParseError, TooManyPoints
from app.routes.params import MAX_RAW_POINTS
from app.routes.parse import parse_gpx
from app.routes.summary import summarise_gpx
from tests.routes.http_helpers import URL, assert_error

POINT = b'<trkpt lat="0" lon="0"/>'
RTEPT = b'<rtept lat="0" lon="0"/>'
CAP = 3  # small cap for the table-driven tests
GPX_NS = b"http://www.topografix.com/GPX/1/1"


def gpx_with(points: bytes, *, prolog: bytes = b"") -> bytes:
    return prolog + b"<gpx><trk><trkseg>" + points + b"</trkseg></trk></gpx>"


def rte_with(points: bytes) -> bytes:
    return b"<gpx><rte>" + points + b"</rte></gpx>"


def prefixed(body: bytes) -> bytes:
    return b'<g:gpx xmlns:g="' + GPX_NS + b'">' + body + b"</g:gpx>"


# --- the boundary ---


def test_the_real_cap_is_one_hundred_thousand() -> None:
    assert MAX_RAW_POINTS == 100_000


def test_max_points_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        parse_gpx(gpx_with(POINT * 2), 3)  # type: ignore[call-arg]  # pins keyword-only


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_up_to_max_points_points_parse(count: int) -> None:
    assert len(parse_gpx(gpx_with(POINT * count), max_points=CAP).points) == count


@pytest.mark.parametrize("count", [4, 5, 40])
def test_more_than_max_points_points_raise_too_many_points(count: int) -> None:
    with pytest.raises(TooManyPoints):
        parse_gpx(gpx_with(POINT * count), max_points=CAP)


def test_the_cap_message_does_not_echo_the_file() -> None:
    data = gpx_with(POINT * 4 + b"<name>SECRET-MARKER-8841</name>")
    with pytest.raises(TooManyPoints) as excinfo:
        parse_gpx(data, max_points=CAP)
    assert "SECRET-MARKER-8841" not in excinfo.value.message


def test_exactly_100000_points_parse_and_100001_raise_at_the_default_cap() -> None:
    assert len(parse_gpx(gpx_with(POINT * 100_000)).points) == 100_000
    with pytest.raises(TooManyPoints):
        parse_gpx(gpx_with(POINT * 100_001))


# --- what counts (a point element the pass reads, valid or not) ---

COUNTED_FORMS = [
    pytest.param(b'<trkpt lat="1" lon="2"/>', id="self-closed"),
    pytest.param(b'<trkpt lat="1" lon="2"></trkpt>', id="open-and-close"),
    pytest.param(b'<trkpt\nlat="1" lon="2"/>', id="newline-after-name"),
    pytest.param(b'<trkpt\tlat="1" lon="2"/>', id="tab-after-name"),
    pytest.param(b"<trkpt lat='1' lon='2'/>", id="single-quoted-attributes"),
    pytest.param(b'<trkpt lat="1" lon="2"><ele>5</ele></trkpt>', id="with-ele"),
    pytest.param(
        b'<trkpt lat="1" lon="2"><extensions><a/></extensions></trkpt>',
        id="with-extensions",
    ),
]


@pytest.mark.parametrize("form", COUNTED_FORMS)
def test_each_counted_trkpt_form_is_counted_exactly_once(form: bytes) -> None:
    assert len(parse_gpx(gpx_with(form * 3), max_points=CAP).points) == 3
    with pytest.raises(TooManyPoints):
        parse_gpx(gpx_with(form * 4), max_points=CAP)


def test_a_bare_trkpt_start_tag_is_counted_even_though_it_is_not_valid() -> None:
    """Counted at the start tag, valid or not (3.12): 4 are too many, 3 are invalid."""
    with pytest.raises(TooManyPoints):
        parse_gpx(gpx_with(b"<trkpt>" * 4), max_points=CAP)
    with pytest.raises(InvalidGpx):
        parse_gpx(gpx_with(b"<trkpt/>" * 3), max_points=CAP)


@pytest.mark.parametrize(
    "form",
    [
        pytest.param(b'<rtept lat="1" lon="2"/>', id="rtept"),
        pytest.param(b'<rtept\nlat="1" lon="2"></rtept>', id="rtept-open-close"),
    ],
)
def test_rtept_forms_are_counted_exactly_once(form: bytes) -> None:
    assert len(parse_gpx(rte_with(form * 3), max_points=CAP).points) == 3
    with pytest.raises(TooManyPoints):
        parse_gpx(rte_with(form * 4), max_points=CAP)


def test_a_prefixed_point_in_the_root_namespace_is_counted_and_parsed() -> None:
    point = b'<g:trkpt lat="1" lon="2"/>'
    body = b"<g:trk><g:trkseg>" + point * 3 + b"</g:trkseg></g:trk>"
    assert len(parse_gpx(prefixed(body), max_points=CAP).points) == 3
    over = b"<g:trk><g:trkseg>" + point * 4 + b"</g:trkseg></g:trk>"
    with pytest.raises(TooManyPoints):
        parse_gpx(prefixed(over), max_points=CAP)


def test_a_prefixed_rtept_in_the_root_namespace_is_counted() -> None:
    point = b'<g:rtept lat="1" lon="2"/>'
    assert (
        len(
            parse_gpx(
                prefixed(b"<g:rte>" + point * 3 + b"</g:rte>"), max_points=CAP
            ).points
        )
        == 3
    )
    with pytest.raises(TooManyPoints):
        parse_gpx(prefixed(b"<g:rte>" + point * 4 + b"</g:rte>"), max_points=CAP)


def test_trk_and_rte_points_are_counted_together() -> None:
    both = (
        b"<trk><trkseg>" + POINT * 2 + b"</trkseg></trk><rte>" + RTEPT * 2 + b"</rte>"
    )
    with pytest.raises(TooManyPoints):
        parse_gpx(b"<gpx>" + both + b"</gpx>", max_points=CAP)
    assert parse_gpx(b"<gpx>" + both + b"</gpx>", max_points=4).points


def test_points_are_counted_across_tracks_routes_and_segments() -> None:
    data = (
        b"<gpx><trk><trkseg><trkpt/></trkseg><trkseg><trkpt/></trkseg></trk>"
        b"<trk><trkseg><trkpt/></trkseg></trk><rte><rtept/></rte></gpx>"
    )
    with pytest.raises(TooManyPoints):
        parse_gpx(data, max_points=CAP)
    with pytest.raises(InvalidGpx):  # 4 counted, within a cap of 4, but no lat/lon
        parse_gpx(data, max_points=4)


def test_fifty_thousand_trk_plus_fifty_thousand_rte_points_are_rejected() -> None:
    data = (
        b"<gpx><trk><trkseg>"
        + POINT * 50_001
        + b"</trkseg></trk><rte>"
        + RTEPT * 50_000
        + b"</rte></gpx>"
    )
    with pytest.raises(TooManyPoints):
        parse_gpx(data)


def test_sixty_thousand_of_each_kind_is_rejected_rte_first() -> None:
    data = (
        b"<gpx><rte>"
        + RTEPT * 60_000
        + b"</rte><trk><trkseg>"
        + POINT * 60_000
        + b"</trkseg></trk></gpx>"
    )
    with pytest.raises(TooManyPoints):
        parse_gpx(data)


NOT_COUNTED_FORMS = [
    pytest.param(b"<trkptx/>", id="longer-name"),
    pytest.param(b"<trkpt2/>", id="name-plus-digit"),
    pytest.param(b"<TRKPT/>", id="upper-case"),
    pytest.param(b"<Trkpt/>", id="mixed-case"),
    pytest.param(b"<trkseg/>", id="empty-trkseg"),
    pytest.param(b"<wpt lat='1' lon='2'/>", id="waypoint"),
    pytest.param(b"<rte/>", id="rte-element"),
    pytest.param(b"trkpt/> trkpt ", id="text-that-looks-like-a-tag"),
    pytest.param(b"<!-- <trkpt/> -->", id="inside-a-comment"),
    pytest.param(b"<![CDATA[<trkpt/>]]>", id="inside-cdata"),
    pytest.param(b"<?pi <trkpt/> ?>", id="inside-a-processing-instruction"),
    pytest.param(b"<extensions><trkpt/></extensions>", id="inside-extensions"),
    pytest.param(b"<x:trkpt xmlns:x='urn:other'/>", id="foreign-namespace-prefixed"),
    pytest.param(b"<trkpt xmlns='urn:other'/>", id="foreign-default-namespace"),
]


@pytest.mark.parametrize("form", NOT_COUNTED_FORMS)
def test_other_content_is_not_counted(form: bytes) -> None:
    parse_gpx(gpx_with(form * 50), max_points=CAP)  # must not raise


def test_trkpt_inside_a_wpt_or_directly_under_trk_is_not_counted() -> None:
    wpt = b"<wpt lat='1' lon='2'><extensions>" + POINT * 10 + b"</extensions></wpt>"
    parse_gpx(b"<gpx>" + wpt + b"</gpx>", max_points=CAP)
    direct = b"<gpx><trk>" + POINT * 10 + b"</trk></gpx>"
    assert parse_gpx(direct, max_points=CAP).points == ()


def test_trkpt_tags_in_a_comment_do_not_reject_a_file_with_no_real_points() -> None:
    """The byte scan over-counted these (4 in a comment rejected a 0-point file)."""
    data = gpx_with(b"<!-- <trkpt/><trkpt/><trkpt/><trkpt/> -->")
    assert parse_gpx(data, max_points=CAP).points == ()


def test_trkpt_tags_in_cdata_do_not_reject_a_file_with_no_real_points() -> None:
    data = gpx_with(b"<name><![CDATA[<trkpt/><trkpt/><trkpt/><trkpt/>]]></name>")
    assert parse_gpx(data, max_points=CAP).points == ()


def test_a_double_prefixed_name_is_invalid_gpx_not_a_count() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(gpx_with(b"<a:b:trkpt/>" * 4), max_points=CAP)


# --- the cap aborts the pass ---


def test_100001_points_raise_too_many_points() -> None:
    with pytest.raises(TooManyPoints):
        parse_gpx(gpx_with(POINT * 100_001))


def test_the_cap_counts_trk_and_rte_points_together_at_the_real_cap() -> None:
    data = (
        b"<gpx><trk><trkseg>"
        + POINT * 50_001
        + b"</trkseg></trk><rte>"
        + RTEPT * 50_000
        + b"</rte></gpx>"
    )
    with pytest.raises(TooManyPoints):
        parse_gpx(data)


def test_exactly_100000_points_still_parse() -> None:
    assert len(parse_gpx(gpx_with(POINT * 100_000)).points) == 100_000


def test_too_many_points_is_a_route_parse_error_with_its_code() -> None:
    with pytest.raises(RouteParseError) as excinfo:
        summarise_gpx(gpx_with(POINT * 100_001), "big.gpx")
    assert excinfo.type is TooManyPoints
    assert excinfo.value.code == "too_many_points"
    assert excinfo.value.message


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param(b'<trkpt lat="', id="truncated-tag"),
        pytest.param(b"<<<<", id="garbage-markup"),
        pytest.param(b"<name>\xff\xfe</name>", id="invalid-utf8"),
        pytest.param(b"\xff", id="a-lone-invalid-byte"),
        pytest.param(b"</trkseg></trk></wrong>", id="mismatched-close"),
    ],
)
def test_the_pass_stops_at_the_100001st_point_so_a_bad_tail_is_never_read(
    tail: bytes,
) -> None:
    data = b"<gpx><trk><trkseg>" + POINT * 100_001 + tail
    with pytest.raises(TooManyPoints):
        parse_gpx(data)


def test_a_bad_byte_before_the_100001st_point_wins_by_document_order() -> None:
    data = gpx_with(b"<name>\xff</name>" + POINT * 100_001)
    with pytest.raises(InvalidGpx):
        parse_gpx(data)


def test_a_malformed_tag_before_the_100001st_point_wins_by_document_order() -> None:
    data = gpx_with(b"<<" + POINT * 100_001)
    with pytest.raises(InvalidGpx):
        parse_gpx(data)


# --- precedence ---


def test_a_doctype_beats_the_cap() -> None:
    data = gpx_with(POINT * 100_001, prolog=b'<!DOCTYPE gpx [<!ENTITY x "y">]>')
    with pytest.raises(InvalidGpx):
        parse_gpx(data)


def test_an_unsupported_declared_encoding_beats_the_cap() -> None:
    data = gpx_with(POINT * 100_001, prolog=b'<?xml version="1.0" encoding="x-nope"?>')
    with pytest.raises(InvalidGpx):
        parse_gpx(data)


def test_a_wrong_root_beats_the_cap() -> None:
    data = b"<kml>" + POINT * 100_001 + b"</kml>"
    with pytest.raises(InvalidGpx):
        parse_gpx(data)


@pytest.mark.parametrize("where", ["start", "middle", "end"])
def test_a_nul_byte_anywhere_beats_the_cap(where: str) -> None:
    nul = b"\x00"
    middle = POINT * 50_000 + (nul if where == "middle" else b"") + POINT * 50_001
    data = gpx_with(middle)
    if where == "start":
        data = nul + data
    elif where == "end":
        data += nul
    with pytest.raises(InvalidGpx):
        parse_gpx(data)


def test_a_non_utf8_byte_without_the_cap_is_still_invalid_gpx() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(gpx_with(POINT * 3 + b"<name>\xff\xfe</name>"))


# --- endpoint, through create_app and the real router ---


def test_the_endpoint_answers_422_too_many_points_for_100001_points(
    client: TestClient,
) -> None:
    data = gpx_with(POINT * 100_001)
    assert len(data) < 3 * 1024 * 1024  # well under the 10 MiB upload cap
    response = client.post(
        URL, files={"file": ("big.gpx", data, "application/gpx+xml")}
    )
    assert_error(response, 422, "too_many_points")


def test_the_endpoint_does_not_report_too_many_points_at_exactly_100000(
    client: TestClient,
) -> None:
    """100,000 identical points get past the cap, then fail as too_few_points."""
    data = gpx_with(POINT * 100_000)
    response = client.post(
        URL, files={"file": ("max.gpx", data, "application/gpx+xml")}
    )
    assert_error(response, 422, "too_few_points")


def test_the_endpoint_error_does_not_echo_the_upload(client: TestClient) -> None:
    data = gpx_with(POINT * 100_001 + b"<name>SECRET-MARKER-31337</name>")
    response = client.post(
        URL, files={"file": ("big.gpx", data, "application/gpx+xml")}
    )
    assert response.status_code == 422
    assert "SECRET-MARKER-31337" not in response.text
