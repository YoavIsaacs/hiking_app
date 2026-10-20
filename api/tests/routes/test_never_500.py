"""Checkpoint "0 x 500": random bytes and mutated fixtures never escape as anything
but a RouteParseError (pure layer) or a status in {200, 413, 422} (HTTP layer).

Hypothesis budgets (small, so the suite stays fast under coverage in CI):
  pure layer: 300 random-byte examples + 150 mutated-fixture examples
  HTTP layer:  60 random-byte examples +  60 mutated-fixture examples
plus the fixed nasty payloads below at both layers.
"""

import contextlib
import re

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.models.route import RouteSummary
from app.routes.errors import RouteParseError
from app.routes.summary import summarise_gpx
from tests.fixtures.loader import GPX_DIR
from tests.routes.gpx_builders import gpx_bytes, straight_line
from tests.routes.hostile_shapes import KIB, burst
from tests.routes.http_helpers import URL

SEED_FILES = [
    (GPX_DIR / "derived-modiin-hills-south-rte.gpx").read_bytes(),
    (GPX_DIR / "derived-tel-hadid-no-ele.gpx").read_bytes()[:20_000],
    gpx_bytes([straight_line(40)]),
]

# the round-3 shape (ADR 0004 "Through HTTP"): self-contained, so it is hostile wherever
# it lands; tests/routes/test_expat_tracker.py proves it is refused on its own
BURST_FRAGMENT = (
    b'<z xmlns:p="urn:'
    + b"u" * (1 * KIB - 4)
    + b'"'
    + burst(' p:%s=""', 384 * KIB).encode()
    + b"/>"
)

FRAGMENTS = [
    b"<!DOCTYPE",
    b'<!DOCTYPE gpx [<!ENTITY x "y">]>',
    b'<trkpt lat="x">',
    b'<trkpt lat="1" lon="1">',
    b"<ele>nan</ele>",
    b"<ele>1e999</ele>",
    b"<time>garbage</time>",
    b"<![CDATA[",
    b"]]>",
    b"&#0;",
    b"&bogus;",
    b"<a>" * 3000,
    b"</gpx>",
    b"\x00",
    b"\xef\xbb\xbf",
    b"<?xml version='2.0'?>",
    # shapes that escaped this suite in 1.2 verify: extreme <ele>, declared encodings
    b"<ele>1e308</ele>",
    b"<ele>-1e308</ele>",
    b"<ele>inf</ele>",
    b"<ele>-1000.001</ele>",
    b"<ele>10000.001</ele>",
    b'<?xml version="1.0" encoding="x-unknown"?>',
    b'<?xml version="1.0" encoding="utf-32"?>',
    b'<?xml version="1.0" encoding="shift_jis"?>',
    b'<?xml version="1.0" encoding="utf-7"?>',
    b'<?xml version="1.0" encoding=""?>',
    b'<trkpt lat="0" lon="0"/>' * 50,
    BURST_FRAGMENT,
]

# Targeted mutations: random byte inserts almost always break the XML first, so these
# rewrite a well-formed value in place and the document stays parseable.
EXTREME_ELE = [
    b"1e308",
    b"-1e308",
    b"1.7976931348623157e308",
    b"inf",
    b"-inf",
    b"nan",
    b"-1000.001",
    b"10000.001",
    b"-1000",
    b"10000",
    b"1e999",
    b"99999999999999999999",
    b"",
]
ENCODINGS = [
    b"x-unknown",
    b"utf-32",
    b"UTF-32",
    b"utf-7",
    b"shift_jis",
    b"big5",
    b"UTF-16",
    b"iso-8859-1",
    b"us-ascii",
    b"windows-1252",
    b"utf-8",
    b"",
]
ELE_RE = re.compile(rb"<ele>[^<]*</ele>")
ENCODING_RE = re.compile(rb"encoding\s*=\s*([\"'])[^\"']*")


def fuzz(max_examples: int) -> settings:
    return settings(
        max_examples=max_examples,
        deadline=None,
        derandomize=True,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )


def replace_ele(data: bytes, pick: int, value: bytes) -> bytes:
    """Replace one ``<ele>`` value (chosen by ``pick``) with ``value``."""
    spans = [m.span() for m in ELE_RE.finditer(data)]
    if not spans:
        return data
    start, end = spans[pick % len(spans)]
    return data[:start] + b"<ele>" + value + b"</ele>" + data[end:]


def set_encoding(data: bytes, name: bytes) -> bytes:
    """Declare ``name`` as the encoding, replacing an existing declaration."""
    declaration = b'encoding="' + name + b'"'
    if ENCODING_RE.search(data):
        return ENCODING_RE.sub(declaration, data, count=1)
    return b'<?xml version="1.0" ' + declaration + b"?>" + data


@st.composite
def mutated(draw: st.DrawFn) -> bytes:
    data = bytearray(draw(st.sampled_from(SEED_FILES)))
    for _ in range(draw(st.integers(1, 4))):
        op = draw(
            st.sampled_from(
                ["truncate", "flip", "insert", "delete", "ele", "ele", "encoding"]
            )
        )
        at = draw(st.integers(0, len(data)))
        if op == "ele":
            data = bytearray(
                replace_ele(bytes(data), at, draw(st.sampled_from(EXTREME_ELE)))
            )
        elif op == "encoding":
            data = bytearray(
                set_encoding(bytes(data), draw(st.sampled_from(ENCODINGS)))
            )
        elif op == "truncate":
            del data[at:]
        elif op == "flip" and data:
            data[min(at, len(data) - 1)] = draw(st.integers(0, 255))
        elif op == "insert":
            data[at:at] = draw(st.sampled_from(FRAGMENTS))
        elif data:
            del data[at : at + draw(st.integers(1, 200))]
    return bytes(data)


def pure(data: bytes) -> None:
    with contextlib.suppress(RouteParseError):  # anything else fails the test
        summarise_gpx(data, "fuzz.gpx")


def over_http(client: TestClient, data: bytes) -> None:
    response = client.post(
        URL, files={"file": ("fuzz.gpx", data, "application/gpx+xml")}
    )
    assert response.status_code in {200, 413, 422}, response.text
    if response.status_code == 200:
        RouteSummary.model_validate(response.json())


@fuzz(300)
@given(st.binary(max_size=64 * 1024))
def test_random_bytes_only_raise_route_parse_errors(data: bytes) -> None:
    pure(data)


@fuzz(150)
@given(mutated())
def test_mutated_fixtures_only_raise_route_parse_errors(data: bytes) -> None:
    pure(data)


@fuzz(60)
@given(st.binary(max_size=64 * 1024))
def test_random_bytes_over_http_give_200_413_or_422(
    client: TestClient, data: bytes
) -> None:
    over_http(client, data)


@fuzz(60)
@given(mutated())
def test_mutated_fixtures_over_http_give_200_413_or_422(
    client: TestClient, data: bytes
) -> None:
    over_http(client, data)


def _doc(
    point_attrs: str = 'lat="10" lon="10"', ele: str = "<ele>1</ele>", extra: str = ""
) -> bytes:
    return (
        '<gpx version="1.1" creator="t"><trk><trkseg>'
        '<trkpt lat="10" lon="10"><ele>1</ele></trkpt>'
        f"<trkpt {point_attrs}>{ele}{extra}</trkpt>"
        '<trkpt lat="10.002" lon="10"><ele>3</ele></trkpt></trkseg></trk></gpx>'
    ).encode()


NASTY = {
    "deep-nesting": b"<gpx>" + b"<a>" * 50_000 + b"</a>" * 50_000 + b"</gpx>",
    "unclosed-deep-nesting": b"<gpx>" + b"<a>" * 100_000,
    "nul-bytes": b"\x00" * 5000,
    "bom-only": b"\xef\xbb\xbf",
    "whitespace-only": b" \n\t " * 1000,
    "utf16-bom": b"\xff\xfe<\x00g\x00p\x00x\x00/\x00>\x00",
    "huge-attribute": b'<gpx a="' + b"x" * 2_000_000 + b'"/>',
    "lat-overflow": _doc('lat="1e999" lon="10"'),
    "lat-underflow": _doc('lat="1e-999" lon="10"'),
    "lat-hex": _doc('lat="0x10" lon="10"'),
    "lat-comma": _doc('lat="10,5" lon="10"'),
    "ele-overflow": _doc(ele="<ele>1e999</ele>"),
    "ele-huge-finite": _doc(ele="<ele>1e308</ele>"),
    "ele-text": _doc(ele="<ele>high</ele>"),
    "ele-empty": _doc(ele="<ele/>"),
    "ele-repeated": _doc(ele="<ele>1</ele><ele>2</ele>"),
    "time-garbage": _doc(extra="<time>not a time</time>"),
    "time-dst-gap": _doc(extra="<time>2026-03-27T02:30:00+02:00</time>"),
    "time-year-0": _doc(extra="<time>0000-01-01T00:00:00Z</time>"),
    "time-year-99999": _doc(extra="<time>99999-01-01T00:00:00Z</time>"),
    "negative-zero": _doc('lat="-0.0" lon="-0.0"'),
    "extensions": _doc(extra="<extensions><x:y xmlns:x='urn:q'>1</x:y></extensions>"),
    "xml-stylesheet": b'<?xml-stylesheet href="x"?>' + _doc(),
    "processing-instruction-first": b"<?pi data?><!-- c -->" + _doc(),
    "namespace-prefixed-root": b'<g:gpx xmlns:g="http://www.topografix.com/GPX/1/1"/>',
    "entity-in-attr": _doc('lat="&amp;" lon="10"'),
    "two-roots": _doc() + _doc(),
    "text-before-root": b"hello" + _doc(),
}


@pytest.mark.parametrize("name", NASTY)
def test_nasty_payloads_only_raise_route_parse_errors(name: str) -> None:
    pure(NASTY[name])


@pytest.mark.parametrize("name", NASTY)
def test_nasty_payloads_over_http_give_200_or_422(
    client: TestClient, name: str
) -> None:
    over_http(client, NASTY[name])


def test_the_hostile_corpus_includes_a_payload_the_pipeline_accepts() -> None:
    """Guards the fuzz seeds: the unmutated seeds are valid GPX."""
    for seed in (SEED_FILES[0], SEED_FILES[2]):
        assert summarise_gpx(seed, None).point_count_original >= 2
