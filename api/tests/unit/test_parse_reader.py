"""Unit tests for the internals of the expat reader (ADR 0004 section 3.1)."""

import math

import pytest

from app.routes import parse
from app.routes.errors import InvalidGpx
from app.routes.parse import _encoding_supported, _parse_float, parse_gpx


@pytest.mark.parametrize("name", ["UTF-8", "utf-8", "utf8", "ISO-8859-1", "latin-1"])
def test_single_byte_and_utf8_encodings_are_supported(name: str) -> None:
    assert _encoding_supported(name)


@pytest.mark.parametrize(
    "name", ["utf-16", "utf-32", "utf-7", "shift_jis", "big5", "nope", "hex"]
)
def test_other_encodings_are_not_supported(name: str) -> None:
    assert not _encoding_supported(name)


@pytest.mark.parametrize(
    ("text", "expected"),
    [(" 1.5 ", 1.5), ("1e2", 100.0), ("-3", -3.0), ("", None), ("x", None)],
)
def test_parse_float(text: str, expected: float | None) -> None:
    assert _parse_float(text) == expected


@pytest.mark.parametrize("text", [None, "nan", "inf", "-inf", "1e999"])
def test_parse_float_rejects_missing_and_non_finite(text: str | None) -> None:
    assert _parse_float(text) is None


def test_parse_float_returns_finite_floats() -> None:
    value = _parse_float("12.25")
    assert value is not None and math.isfinite(value)


def test_a_declared_unsupported_encoding_is_invalid_gpx() -> None:
    with pytest.raises(InvalidGpx, match="encoding"):
        parse_gpx(b'<?xml version="1.0" encoding="utf-7"?><gpx/>')


def test_tokens_split_across_input_chunks_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parse, "_CHUNK_BYTES", 3)
    doc = (
        "<gpx><metadata><name>Café א</name></metadata><trk><trkseg>"
        '<trkpt lat="1.25" lon="2.5"><ele>12</ele></trkpt>'
        '<trkpt lat="2" lon="3"/></trkseg></trk></gpx>'
    )
    raw = parse_gpx(doc.encode())
    assert raw.metadata_name == "Café א"
    assert [(p.lat, p.lon, p.elev_m) for p in raw.points] == [
        (1.25, 2.5, 12.0),
        (2.0, 3.0, None),
    ]


def test_a_failed_parse_leaves_no_state_for_the_next_call() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(b'<gpx><trk><trkseg><trkpt lat="1" lon="1"><ele>5')
    raw = parse_gpx(b'<gpx><trk><trkseg><trkpt lat="1" lon="1"/></trkseg></trk></gpx>')
    assert [p.elev_m for p in raw.points] == [None]
