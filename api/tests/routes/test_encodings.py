"""Declared and actual XML encodings (ADR 0004 section 3.11): never a 500.

An unsupported declared encoding is ``invalid_gpx`` (expat raises LookupError or
ValueError for them). UTF-8 is the only accepted content encoding.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routes.errors import InvalidGpx, TooManyPoints
from app.routes.parse import parse_gpx
from app.routes.summary import summarise_gpx
from app.routes.xml_guard import check_gpx_prolog
from tests.routes.gpx_builders import gpx_bytes, straight_line
from tests.routes.http_helpers import URL, assert_error

BODY = (
    '<gpx version="1.1" creator="t"><trk><trkseg>'
    '<trkpt lat="1" lon="1"><ele>5</ele></trkpt>'
    '<trkpt lat="1.001" lon="1"><ele>6</ele></trkpt>'
    "</trkseg></trk></gpx>"
)


def declared(encoding: str, body: str = BODY) -> bytes:
    return f'<?xml version="1.0" encoding="{encoding}"?>{body}'.encode()


# LookupError from expat (unknown name) and ValueError (known but unsupported).
UNSUPPORTED = [
    "x-unknown",
    "utf-32",
    "UTF-32",
    "utf-7",
    "shift_jis",
    "big5",
    "",
    "nope",
]


@pytest.fixture
def tolerant_client(settings: Settings) -> TestClient:
    """Returns a 500 as a response instead of re-raising it in the test."""
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.mark.parametrize("encoding", UNSUPPORTED)
def test_check_gpx_prolog_rejects_an_unsupported_declared_encoding(
    encoding: str,
) -> None:
    with pytest.raises(InvalidGpx):
        check_gpx_prolog(declared(encoding))


@pytest.mark.parametrize("encoding", UNSUPPORTED)
def test_summarise_gpx_rejects_an_unsupported_declared_encoding(
    encoding: str,
) -> None:
    with pytest.raises(InvalidGpx):
        summarise_gpx(declared(encoding), "f.gpx")


@pytest.mark.parametrize("encoding", UNSUPPORTED)
def test_an_unsupported_declared_encoding_over_http_is_422_invalid_gpx(
    tolerant_client: TestClient, encoding: str
) -> None:
    response = tolerant_client.post(
        URL, files={"file": ("f.gpx", declared(encoding), "application/gpx+xml")}
    )
    assert_error(response, 422, "invalid_gpx")


@pytest.mark.parametrize("quote", ['"', "'"])
def test_single_quoted_declarations_are_handled_the_same(
    tolerant_client: TestClient, quote: str
) -> None:
    data = f"<?xml version={quote}1.0{quote} encoding={quote}utf-32{quote}?>{BODY}"
    response = tolerant_client.post(
        URL, files={"file": ("f.gpx", data.encode(), "application/gpx+xml")}
    )
    assert_error(response, 422, "invalid_gpx")


@pytest.mark.parametrize("encoding", ["utf-8", "UTF-8", "Utf-8"])
def test_a_declared_utf8_encoding_is_accepted(
    tolerant_client: TestClient, encoding: str
) -> None:
    response = tolerant_client.post(
        URL, files={"file": ("f.gpx", declared(encoding), "application/gpx+xml")}
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("encoding", ["iso-8859-1", "us-ascii", "windows-1252"])
def test_other_supported_declarations_on_ascii_content_never_return_500(
    tolerant_client: TestClient, encoding: str
) -> None:
    response = tolerant_client.post(
        URL, files={"file": ("f.gpx", declared(encoding), "application/gpx+xml")}
    )
    assert response.status_code in {200, 422}, response.text


def test_latin1_bytes_declared_as_latin1_are_invalid_gpx_not_a_500(
    tolerant_client: TestClient,
) -> None:
    body = BODY.replace("<trk>", "<metadata><name>Caf\xe9</name></metadata><trk>")
    data = declared("iso-8859-1", body).decode("utf-8").encode("latin-1")
    response = tolerant_client.post(
        URL, files={"file": ("f.gpx", data, "application/gpx+xml")}
    )
    assert_error(response, 422, "invalid_gpx")


@pytest.mark.parametrize("codec", ["utf-16", "utf-16-le", "utf-16-be", "utf-32"])
def test_a_file_saved_as_utf16_or_utf32_is_invalid_gpx(
    tolerant_client: TestClient, codec: str
) -> None:
    text = f'<?xml version="1.0"?>{BODY}'
    data = text.encode(codec)
    if codec in {"utf-16", "utf-32"}:
        assert data[:2] in {b"\xff\xfe", b"\x00\x00"}  # a byte-order mark was written
    response = tolerant_client.post(
        URL, files={"file": ("f.gpx", data, "application/gpx+xml")}
    )
    assert_error(response, 422, "invalid_gpx")


def test_a_utf8_bom_before_the_declaration_is_accepted(
    tolerant_client: TestClient,
) -> None:
    data = gpx_bytes([straight_line(5)], bom=True)
    assert data.startswith(b"\xef\xbb\xbf")
    response = tolerant_client.post(
        URL, files={"file": ("f.gpx", data, "application/gpx+xml")}
    )
    assert response.status_code == 200, response.text


def test_the_error_message_names_the_encoding_problem_without_echoing_the_file(
    tolerant_client: TestClient,
) -> None:
    body = BODY.replace("<trk>", "<metadata><name>SECRET-7f3a</name></metadata><trk>")
    response = tolerant_client.post(
        URL,
        files={"file": ("f.gpx", declared("shift_jis", body), "application/gpx+xml")},
    )
    assert_error(response, 422, "invalid_gpx")
    assert "SECRET-7f3a" not in response.text


@pytest.mark.parametrize("codec", ["utf-16-le", "utf-16-be"])
def test_bomless_utf16_cannot_smuggle_points_past_the_point_cap(
    codec: str,
) -> None:
    """The cap scans raw bytes for ASCII tags (ADR 3.12 relies on "step 4 requires
    UTF-8"). NUL-interleaved UTF-16 decodes as UTF-8, and expat then auto-detects
    UTF-16, so the tags are invisible to the scan but gpxpy builds every point."""
    point = '<trkpt lat="0" lon="0"/>'
    text = "<gpx><trk><trkseg>" + point * 100_001 + "</trkseg></trk></gpx>"
    with pytest.raises((InvalidGpx, TooManyPoints)):
        parse_gpx(text.encode(codec))
