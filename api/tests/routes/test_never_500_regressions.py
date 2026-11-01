"""Step 1.2 verify findings: inputs the fuzz budget missed that escaped as HTTP 500.

Checkpoint "0 responses with status 500". Each case must be a 200 or a typed 422,
from the pure pipeline (RouteParseError only) and through the real app.
"""

import contextlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.config import Settings
from app.main import create_app
from app.models.route import RouteSummary
from app.routes.errors import RouteParseError
from app.routes.summary import summarise_gpx
from tests.elevation_support import ElevationApi
from tests.routes.http_helpers import URL


@pytest.fixture
def tolerant_client(
    settings: Settings, elevation_api: ElevationApi
) -> Iterator[TestClient]:
    """Returns the 500 response instead of re-raising it in the test.

    Runs the app with its lifespan: files with an implausible ``<ele>`` are backfilled
    from the (respx) lookup, offline.
    """
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        yield c


def _doc(elevations: list[str], prolog: bytes = b"") -> bytes:
    pts = "".join(
        f'<trkpt lat="{40 + i * 0.001}" lon="10"><ele>{e}</ele></trkpt>'
        for i, e in enumerate(elevations)
    )
    return prolog + f"<gpx><trk><trkseg>{pts}</trkseg></trk></gpx>".encode()


OVERFLOWING_ELEVATIONS = [
    pytest.param(["1e308", "-1e308", "1e308"], id="alternating-1e308"),
    pytest.param(["1e308", "-1e308"] * 20, id="many-1e308-swings"),
    pytest.param(
        ["-1.7976931348623157e308", "1.7976931348623157e308"] * 3, id="float-max"
    ),
]

UNKNOWN_ENCODINGS = [
    pytest.param(b'<?xml version="1.0" encoding="nope"?>', id="unknown-name"),
    pytest.param(
        b'<?xml version="1.0" encoding="x-user-defined"?>', id="x-user-defined"
    ),
    pytest.param(b'<?xml version="1.0" encoding=""?>', id="empty-name"),
]


def _assert_pure_ok_or_parse_error(data: bytes) -> None:
    with contextlib.suppress(RouteParseError):  # anything else fails the test
        summarise_gpx(data, "f.gpx")


@pytest.mark.parametrize("elevations", OVERFLOWING_ELEVATIONS)
def test_extreme_elevations_never_overflow_the_summary_pure(
    elevations: list[str],
) -> None:
    _assert_pure_ok_or_parse_error(_doc(elevations))


@pytest.mark.parametrize("elevations", OVERFLOWING_ELEVATIONS)
def test_extreme_elevations_never_return_500(
    tolerant_client: TestClient, elevations: list[str]
) -> None:
    r = tolerant_client.post(URL, files={"file": ("f.gpx", _doc(elevations))})
    assert r.status_code in {200, 422}, r.text
    if r.status_code == 200:
        RouteSummary.model_validate(r.json())  # finite numbers only


@pytest.mark.parametrize("prolog", UNKNOWN_ENCODINGS)
def test_unknown_xml_encoding_is_invalid_gpx_pure(prolog: bytes) -> None:
    with pytest.raises(RouteParseError):
        summarise_gpx(_doc(["1", "2"], prolog), "f.gpx")


@pytest.mark.parametrize("prolog", UNKNOWN_ENCODINGS)
def test_unknown_xml_encoding_returns_422_invalid_gpx(
    tolerant_client: TestClient, prolog: bytes
) -> None:
    r = tolerant_client.post(URL, files={"file": ("f.gpx", _doc(["1", "2"], prolog))})
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "invalid_gpx"


@settings(
    max_examples=200,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    st.lists(
        st.floats(allow_nan=False, allow_infinity=False, width=64),
        min_size=2,
        max_size=40,
    )
)
def test_any_finite_elevations_only_return_or_raise_parse_error(
    elevations: list[float],
) -> None:
    _assert_pure_ok_or_parse_error(_doc([repr(e) for e in elevations]))
