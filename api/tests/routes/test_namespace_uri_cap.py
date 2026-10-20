"""The namespace URI cap (ADR 0004 amendment, item 37; 3.1 step 4 and step 5).

Any declared namespace URI longer than 1,024 decoded characters is refused with 422
``invalid_gpx`` "The file is too complex to parse.", for default and prefixed
declarations, on the root and on any other element. ``xmlns=""`` is accepted. Precedence
is document order.

Written against the public surface only (``parse_gpx``, ``summarise_gpx``, HTTP), with
the literal 1,024: the constant itself is pinned at verify time.
"""

import re
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.routes.errors import InvalidGpx, TooManyPoints
from app.routes.parse import parse_gpx
from app.routes.summary import summarise_gpx
from tests.fixtures.loader import Expected, fixture_params, valid_fixtures
from tests.routes.hostile_shapes import (
    KIB,
    MIB,
    burst,
    last_json_line,
    run_python,
)
from tests.routes.http_helpers import URL, assert_error

Builder = Callable[[str], bytes]
LIMIT = 1024
TOO_COMPLEX = "The file is too complex to parse."
NOT_WELL_FORMED = "The file is not well-formed XML"
FOUR_BYTE = "\U00010000"
PT1 = '<trkpt lat="1" lon="1"/>'
PT2 = '<trkpt lat="2" lon="2"/>'


def uri(n: int) -> str:
    """An ASCII URI of exactly ``n`` characters."""
    return "urn:" + "u" * (n - 4)


def encode(doc: str) -> bytes:
    return doc.encode("utf-8")


# --- one document per place a declaration can sit; each takes the URI text ---


def default_on_root(u: str) -> bytes:
    pts = f"<trk><trkseg>{PT1}{PT2}</trkseg></trk>"
    return encode(f'<gpx xmlns="{u}">{pts}</gpx>')


def prefixed_on_root(u: str) -> bytes:
    pts = (
        "<p:trk><p:trkseg>"
        '<p:trkpt lat="1" lon="1"/><p:trkpt lat="2" lon="2"/>'
        "</p:trkseg></p:trk>"
    )
    return encode(f'<p:gpx xmlns:p="{u}">{pts}</p:gpx>')


def prefixed_on_child(u: str) -> bytes:
    return encode(f'<gpx><trk xmlns:x="{u}"><trkseg>{PT1}{PT2}</trkseg></trk></gpx>')


def default_on_child(u: str) -> bytes:
    pt = f'<trkpt lat="1" lon="1"><extensions xmlns="{u}"/></trkpt>'
    return encode(f"<gpx><trk><trkseg>{pt}{PT2}</trkseg></trk></gpx>")


PLACES = {
    "default-on-root": default_on_root,
    "prefixed-on-root": prefixed_on_root,
    "prefixed-on-child": prefixed_on_child,
    "default-on-child": default_on_child,
}
place = pytest.mark.parametrize("build", list(PLACES.values()), ids=list(PLACES))


def refusal(data: bytes) -> InvalidGpx:
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(data)
    return excinfo.value


# --- the boundary ---


@place
def test_a_uri_of_exactly_1024_characters_is_accepted(build: Builder) -> None:
    assert len(parse_gpx(build(uri(LIMIT))).points) == 2


@place
def test_a_uri_of_1025_characters_is_refused_as_too_complex(build: Builder) -> None:
    assert refusal(build(uri(LIMIT + 1))).message == TOO_COMPLEX


@place
def test_a_refused_uri_is_the_handler_not_an_expat_failure(build: Builder) -> None:
    """The guard against the tracker taking over: it is not an ExpatError cause."""
    exc = refusal(build(uri(LIMIT + 1)))
    assert exc.message == TOO_COMPLEX
    assert exc.__cause__ is None


@place
def test_a_uri_far_over_the_cap_is_refused(build: Builder) -> None:
    assert refusal(build(uri(64 * KIB))).message == TOO_COMPLEX


def test_a_long_declaration_inside_a_skipped_subtree_is_refused() -> None:
    wpt = f'<wpt lat="0" lon="0"><extensions xmlns:q="{uri(LIMIT + 1)}"/></wpt>'
    data = encode(f"<gpx>{wpt}<trk><trkseg>{PT1}{PT2}</trkseg></trk></gpx>")
    assert refusal(data).message == TOO_COMPLEX


def test_the_refusal_applies_through_summarise_gpx_too() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        summarise_gpx(default_on_root(uri(LIMIT + 1)), "f.gpx")
    assert excinfo.value.message == TOO_COMPLEX


# --- characters, not bytes ---


@place
def test_1024_four_byte_characters_are_accepted(build: Builder) -> None:
    assert len(parse_gpx(build(FOUR_BYTE * LIMIT)).points) == 2


@place
def test_1025_four_byte_characters_are_refused(build: Builder) -> None:
    assert refusal(build(FOUR_BYTE * (LIMIT + 1))).message == TOO_COMPLEX


@place
def test_300_four_byte_characters_about_1_2_kb_are_accepted(build: Builder) -> None:
    data = build(FOUR_BYTE * 300)
    assert len(FOUR_BYTE.encode()) * 300 == 1200
    assert len(parse_gpx(data).points) == 2


def test_character_references_count_once_each() -> None:
    def doc(n: int) -> bytes:
        refs = "&#x75;" * n
        pts = f"<trk><trkseg>{PT1}{PT2}</trkseg></trk>"
        return encode(f'<gpx xmlns:x="{refs}">{pts}</gpx>')

    assert len(parse_gpx(doc(LIMIT)).points) == 2  # 6,144 source bytes
    assert refusal(doc(LIMIT + 1)).message == TOO_COMPLEX


# --- undeclaration ---


def test_xmlns_empty_on_a_child_is_accepted() -> None:
    data = encode(
        f'<gpx xmlns="{uri(50)}"><trk><trkseg xmlns="">{PT1}{PT2}</trkseg></trk></gpx>'
    )
    parse_gpx(data)  # not refused; those points are outside the root namespace


def test_xmlns_empty_on_a_child_of_a_long_default_namespace_root_is_accepted() -> None:
    pts = f"<trk><trkseg>{PT1}{PT2}</trkseg></trk>"
    data = encode(f'<gpx xmlns="{uri(LIMIT)}">{pts}<extensions xmlns=""/></gpx>')
    assert len(parse_gpx(data).points) == 2


# --- through the real wiring: create_app -> router -> summarise_gpx -> parse_gpx ---


@place
def test_a_1025_character_uri_posted_is_422_too_complex_and_never_a_500(
    client: TestClient,
    build: Builder,
) -> None:
    response = client.post(
        URL, files={"file": ("long.gpx", build(uri(LIMIT + 1)), "application/gpx+xml")}
    )
    body = assert_error(response, 422, "invalid_gpx")
    assert body == {"code": "invalid_gpx", "message": TOO_COMPLEX, "detail": None}


@place
def test_a_1024_character_uri_posted_is_accepted(
    client: TestClient,
    build: Builder,
) -> None:
    response = client.post(
        URL, files={"file": ("ok.gpx", build(uri(LIMIT)), "application/gpx+xml")}
    )
    assert response.status_code == 200, response.text


# --- precedence is document order (ADR 3.1 step 5) ---
# Each hostile part is first proven hostile on its own (the guards), so a combination
# cannot pass or fail because one part was never hostile.

LONG = uri(LIMIT + 1)
LONG_DECL = f'<x:y xmlns:x="{LONG}"/>'
OVER_CAP_POINTS = (PT1 * 100_001).encode()


def test_guard_100001_points_alone_give_too_many_points() -> None:
    with pytest.raises(TooManyPoints):
        parse_gpx(b"<gpx><trk><trkseg>" + OVER_CAP_POINTS + b"</trkseg></trk></gpx>")


def test_guard_the_long_uri_alone_is_too_complex() -> None:
    assert refusal(encode(f"<gpx>{LONG_DECL}</gpx>")).message == TOO_COMPLEX


def test_guard_the_malformation_alone_is_not_well_formed() -> None:
    assert refusal(b"<gpx><a></b></gpx>").message.startswith(NOT_WELL_FORMED)


def test_100001_points_and_then_a_long_uri_give_too_many_points() -> None:
    data = (
        b"<gpx><trk><trkseg>"
        + OVER_CAP_POINTS
        + b"</trkseg></trk>"
        + encode(LONG_DECL)
        + b"</gpx>"
    )
    with pytest.raises(TooManyPoints):
        parse_gpx(data)


def test_a_long_uri_and_then_100001_points_give_too_complex() -> None:
    data = (
        b"<gpx>"
        + encode(LONG_DECL)
        + b"<trk><trkseg>"
        + OVER_CAP_POINTS
        + b"</trkseg></trk></gpx>"
    )
    assert refusal(data).message == TOO_COMPLEX


def test_a_malformation_and_then_a_long_uri_give_not_well_formed() -> None:
    data = encode(f"<gpx><a></b>{LONG_DECL}</gpx>")
    assert refusal(data).message.startswith(NOT_WELL_FORMED)


def test_a_long_uri_and_then_a_malformation_give_too_complex() -> None:
    data = encode(f"<gpx>{LONG_DECL}<a></b></gpx>")
    assert refusal(data).message == TOO_COMPLEX


def test_a_long_uri_on_a_non_gpx_root_gives_too_complex_not_not_gpx() -> None:
    assert refusal(encode(f'<kml xmlns="{LONG}"/>')).message == TOO_COMPLEX


# --- the measured shape: refused fast ---

# ADR H4: distinct p:-prefixed children of <gpx xmlns:p="U">, names shortest-first.
H4_CHILD = """
    import sys, time
    from app.routes.errors import InvalidGpx
    from app.routes.parse import parse_gpx

    data = sys.stdin.buffer.read()
    started = time.perf_counter()
    try:
        outcome, message, cause = f"{len(parse_gpx(data).points)} points", None, None
    except InvalidGpx as exc:
        outcome, message, cause = "invalid_gpx", exc.message, exc.__cause__
    seconds = time.perf_counter() - started
    import json
    print(json.dumps({
        "outcome": outcome, "message": message, "has_cause": cause is not None,
        "seconds": seconds,
    }))
"""


def h4_document(size: int, uri_chars: int) -> bytes:
    head = f'<gpx xmlns:p="{uri(uri_chars)}">'
    return (head + burst("<p:%s/>", size - len(head) - 6) + "</gpx>").encode()


def test_the_10_mib_h4_shape_at_a_64_kib_uri_is_refused_in_under_a_second() -> None:
    data = h4_document(10 * MIB, 64 * KIB)
    assert 10 * MIB - 64 <= len(data) <= 10 * MIB
    out = last_json_line(run_python(textwrap.dedent(H4_CHILD), data, timeout_s=120))
    assert out["outcome"] == "invalid_gpx", out
    assert out["message"] == TOO_COMPLEX, out
    assert out["has_cause"] is False, out  # the handler, not the tracker
    seconds = out["seconds"]
    assert isinstance(seconds, float) and seconds < 1.0, out


# --- legitimate files are unaffected ---

XMLNS_DECL = re.compile(r"""xmlns(?::[\w.-]+)?\s*=\s*(?:"([^"]*)"|'([^']*)')""")


@pytest.mark.parametrize(("path", "expected"), fixture_params(valid_fixtures()))
def test_every_valid_fixture_is_still_accepted_and_declares_short_uris(
    path: Path, expected: Expected
) -> None:
    raw = path.read_bytes()
    declared = [
        a or b for a, b in XMLNS_DECL.findall(raw.decode("utf-8", errors="replace"))
    ]
    assert max((len(u) for u in declared), default=0) <= 53
    assert parse_gpx(raw).points
