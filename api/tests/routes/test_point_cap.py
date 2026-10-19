"""The raw point cap (ADR 0004 section 3.12): a byte scan that runs before gpxpy.

Unit tests of ``exceeds_point_cap``, the cap inside ``parse_gpx`` (including error
precedence), and the endpoint answer (422 ``too_many_points``).
"""

import time

import gpxpy
import pytest
from fastapi.testclient import TestClient

from app.routes.errors import InvalidGpx, RouteParseError, TooManyPoints
from app.routes.params import MAX_RAW_POINTS
from app.routes.parse import parse_gpx
from app.routes.summary import summarise_gpx
from app.routes.xml_guard import exceeds_point_cap
from tests.routes.http_helpers import URL, assert_error

POINT = b'<trkpt lat="0" lon="0"/>'
CAP = 3  # small cap for the table-driven unit tests


def gpx_with(points: bytes, *, prolog: bytes = b"") -> bytes:
    return prolog + b"<gpx><trk><trkseg>" + points + b"</trkseg></trk></gpx>"


# --- exceeds_point_cap: the boundary -----------------------------------------------


def test_the_real_cap_is_one_hundred_thousand() -> None:
    assert MAX_RAW_POINTS == 100_000


@pytest.mark.parametrize(("count", "expected"), [(0, False), (3, False), (4, True)])
def test_the_cap_boundary_is_exclusive_of_max_points(
    count: int, expected: bool
) -> None:
    assert exceeds_point_cap(POINT * count, max_points=CAP) is expected


def test_exactly_100000_tags_pass_and_100001_exceed_at_the_default_cap() -> None:
    assert exceeds_point_cap(POINT * 100_000) is False
    assert exceeds_point_cap(POINT * 100_001) is True


# --- what counts --------------------------------------------------------------------

COUNTED_FORMS = [
    pytest.param(b"<trkpt>", id="bare-open-tag"),
    pytest.param(b"<trkpt/>", id="self-closed"),
    pytest.param(b'<trkpt lat="1" lon="2">', id="with-attributes"),
    pytest.param(b"<trkpt\nlat='1' lon='2'/>", id="newline-after-name"),
    pytest.param(b"<trkpt\tlat='1' lon='2'/>", id="tab-after-name"),
    pytest.param(b'<gpx:trkpt lat="1" lon="2"/>', id="prefixed"),
    pytest.param(b"<a:b:trkpt/>", id="double-prefix"),
    pytest.param(b"<rtept/>", id="rtept"),
    pytest.param(b'<rtept lat="1" lon="2">', id="rtept-attributes"),
    pytest.param(b"<gpx:rtept/>", id="prefixed-rtept"),
    pytest.param(b"<!-- <trkpt/> -->", id="inside-a-comment-over-counts"),
    pytest.param(b"<![CDATA[<trkpt/>]]>", id="inside-cdata-over-counts"),
]


@pytest.mark.parametrize("form", COUNTED_FORMS)
def test_each_counted_form_is_counted_exactly_once(form: bytes) -> None:
    assert exceeds_point_cap(form * 3, max_points=CAP) is False
    assert exceeds_point_cap(form * 4, max_points=CAP) is True


def test_comment_over_count_is_the_documented_behaviour() -> None:
    """Pinned, not endorsed: 4 tags in comments reject a file with 0 real points."""
    data = gpx_with(b"<!-- <trkpt/><trkpt/><trkpt/><trkpt/> -->")
    assert exceeds_point_cap(data, max_points=CAP) is True


def test_trkpt_and_rtept_are_counted_together() -> None:
    assert exceeds_point_cap(b"<trkpt/><trkpt/><rtept/>", max_points=CAP) is False
    assert (
        exceeds_point_cap(b"<trkpt/><trkpt/><rtept/><rtept/>", max_points=CAP) is True
    )


def test_tags_are_counted_across_tracks_routes_and_segments() -> None:
    data = (
        b"<gpx><trk><trkseg><trkpt/></trkseg><trkseg><trkpt/></trkseg></trk>"
        b"<trk><trkseg><trkpt/></trkseg></trk><rte><rtept/></rte></gpx>"
    )
    assert exceeds_point_cap(data, max_points=CAP) is True
    assert exceeds_point_cap(data, max_points=4) is False


NOT_COUNTED_FORMS = [
    pytest.param(b"</trkpt>", id="closing-tag"),
    pytest.param(b"</rtept>", id="closing-rtept"),
    pytest.param(b"<trkptx/>", id="longer-name"),
    pytest.param(b"<trkpt2>", id="name-plus-digit"),
    pytest.param(b"<TRKPT/>", id="upper-case"),
    pytest.param(b"<Trkpt/>", id="mixed-case"),
    pytest.param(b"<trkseg>", id="trkseg"),
    pytest.param(b"<wpt lat='1' lon='2'/>", id="waypoint"),
    pytest.param(b"<rte>", id="rte-element"),
    pytest.param(b"<gpx:trkptx/>", id="prefixed-longer-name"),
    pytest.param(b"trkpt/> trkpt ", id="no-angle-bracket"),
]


@pytest.mark.parametrize("form", NOT_COUNTED_FORMS)
def test_other_tags_are_not_counted(form: bytes) -> None:
    assert exceeds_point_cap(form * 50, max_points=CAP) is False


def test_a_closing_tag_next_to_a_real_one_does_not_double_count() -> None:
    data = b"<trkpt></trkpt>" * 3  # 3 real points, 3 closing tags
    assert exceeds_point_cap(data, max_points=CAP) is False


# --- linear time on adversarial bytes -------------------------------------------------

TEN_MIB = 10 * 1024 * 1024
WALL_BOUND_S = 2.0  # generous: the scan takes ~0.1-0.5 s; a quadratic one takes minutes


def _adversarial() -> dict[str, bytes]:
    return {
        "short-runs-of-a": b"<a" * (TEN_MIB // 2),
        "runs-of-50": (b"<" + b"a" * 50) * (TEN_MIB // 51),
        "runs-of-5000": (b"<" + b"a" * 5000) * (TEN_MIB // 5001),
        "one-giant-run": b"<" + b"a" * TEN_MIB,
        "prefix-colons": b"<" + b"a:" * (TEN_MIB // 2),
        "only-angle-brackets": b"<" * TEN_MIB,
        "long-prefix-then-near-miss": (b"<" + b"a:" * 2000 + b"trkp")
        * (TEN_MIB // 4005),
        "prefixed-points": b"<gpx:trkpt/>" * (TEN_MIB // 12),
    }


@pytest.mark.parametrize("name", list(_adversarial()))
def test_the_scan_is_linear_on_ten_mib_of_adversarial_input(name: str) -> None:
    data = _adversarial()[name]
    started = time.perf_counter()
    exceeds_point_cap(data)
    assert time.perf_counter() - started < WALL_BOUND_S


# --- parse_gpx: the cap runs before gpxpy ---------------------------------------------


@pytest.fixture
def gpxpy_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Replaces ``gpxpy.parse`` with a recorder that fails if it is ever reached."""
    calls: list[int] = []

    def forbidden(*_args: object, **_kwargs: object) -> None:
        calls.append(1)
        raise AssertionError("gpxpy.parse must not run for an over-cap file")

    monkeypatch.setattr(gpxpy, "parse", forbidden)
    return calls


def test_100001_points_raise_too_many_points_without_calling_gpxpy(
    gpxpy_calls: list[int],
) -> None:
    with pytest.raises(TooManyPoints):
        parse_gpx(gpx_with(POINT * 100_001))
    assert gpxpy_calls == []


def test_the_cap_counts_trk_and_rte_points_together_before_gpxpy(
    gpxpy_calls: list[int],
) -> None:
    data = (
        b"<gpx><trk><trkseg>"
        + POINT * 50_001
        + b"</trkseg></trk><rte>"
        + b'<rtept lat="0" lon="0"/>' * 50_000
        + b"</rte></gpx>"
    )
    with pytest.raises(TooManyPoints):
        parse_gpx(data)
    assert gpxpy_calls == []


def test_exactly_100000_points_still_parse() -> None:
    assert len(parse_gpx(gpx_with(POINT * 100_000)).points) == 100_000


def test_too_many_points_is_a_route_parse_error_with_its_code() -> None:
    with pytest.raises(RouteParseError) as excinfo:
        summarise_gpx(gpx_with(POINT * 100_001), "big.gpx")
    assert excinfo.type is TooManyPoints
    assert excinfo.value.code == "too_many_points"
    assert excinfo.value.message


# --- precedence: prolog error > too_many_points > not UTF-8 > gpxpy failure ----------


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


def test_the_cap_beats_a_non_utf8_byte() -> None:
    data = gpx_with(POINT * 100_001 + b"<name>\xff\xfe</name>")
    with pytest.raises(TooManyPoints):
        parse_gpx(data)


def test_the_cap_beats_a_gpxpy_failure() -> None:
    truncated = b"<gpx><trk><trkseg>" + POINT * 100_001 + b"<trkpt lat="
    with pytest.raises(TooManyPoints):
        parse_gpx(truncated)


def test_a_non_utf8_byte_without_the_cap_is_still_invalid_gpx() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(gpx_with(POINT * 3 + b"<name>\xff\xfe</name>"))


# --- endpoint, through create_app and the real router ---------------------------------


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
