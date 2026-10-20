"""Plausible elevation range [-1000, 10000] m, inclusive (ADR 0004 3.1 step 8).

An ``<ele>`` outside the range is treated as missing, and one missing point means the
whole profile is null: ``has_elevation`` false and every ``elev_m`` null.
"""

import math

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.config import Settings
from app.main import create_app
from app.models.route import RouteSummary
from app.routes.params import MAX_PLAUSIBLE_ELEV_M, MIN_PLAUSIBLE_ELEV_M
from app.routes.parse import parse_gpx
from app.routes.summary import summarise_gpx
from tests.routes.http_helpers import URL

KEPT = [
    ("-1000", -1000.0),
    ("-999.999", -999.999),
    ("0", 0.0),
    ("-430.5", -430.5),
    ("8848.86", 8848.86),
    ("9999.999", 9999.999),
    ("10000", 10000.0),
    ("1e4", 10000.0),
]
DROPPED = [
    "-1000.001",
    "-1000.0000001",
    "10000.001",
    "10000.0000001",
    "-5000",
    "99999",
    "1e308",
    "-1e308",
    "1e999",
    "-1e999",
    "inf",
    "-inf",
    "nan",
]


def doc(elevations: list[str | None]) -> bytes:
    """A track along a meridian, 0.001 degrees (about 111 m) apart; None omits <ele>."""
    pts = "".join(
        f'<trkpt lat="{40 + i * 0.001}" lon="10">'
        + ("" if e is None else f"<ele>{e}</ele>")
        + "</trkpt>"
        for i, e in enumerate(elevations)
    )
    return f"<gpx><trk><trkseg>{pts}</trkseg></trk></gpx>".encode()


def test_the_range_constants_are_the_documented_ones() -> None:
    assert MIN_PLAUSIBLE_ELEV_M == -1000.0
    assert MAX_PLAUSIBLE_ELEV_M == 10000.0


# --- parse_gpx -----------------------------------------------------------------------


@pytest.mark.parametrize(("text", "value"), KEPT)
def test_values_inside_the_range_are_kept_inclusive_of_both_bounds(
    text: str, value: float
) -> None:
    assert parse_gpx(doc(["5", text, "5"])).points[1].elev_m == value


@pytest.mark.parametrize("text", DROPPED)
def test_values_outside_the_range_or_not_finite_become_none(text: str) -> None:
    points = parse_gpx(doc(["5", text, "5"])).points
    assert [p.elev_m for p in points] == [5.0, None, 5.0]


# --- summarise_gpx: the whole profile goes null ---------------------------


@pytest.mark.parametrize("text", DROPPED)
@pytest.mark.parametrize("position", [0, 2, 4], ids=["first", "middle", "last"])
def test_one_implausible_point_nulls_the_whole_profile(
    text: str, position: int
) -> None:
    elevations: list[str | None] = ["100", "120", "150", "130", "110"]
    elevations[position] = text
    summary = summarise_gpx(doc(elevations), "f.gpx")
    assert summary.has_elevation is False
    assert summary.elevation_source == "none"
    assert summary.gain_m is None and summary.loss_m is None
    assert summary.min_elev_m is None and summary.max_elev_m is None
    assert summary.high_point is None
    assert summary.start.elev_m is None and summary.end.elev_m is None
    assert all(p.elev_m is None for p in summary.points)


def test_a_missing_ele_nulls_the_profile_the_same_way() -> None:
    summary = summarise_gpx(doc(["100", None, "150"]), "f.gpx")
    assert summary.has_elevation is False
    assert all(p.elev_m is None for p in summary.points)


def test_bounds_inclusive_everywhere_keeps_the_profile() -> None:
    summary = summarise_gpx(doc(["-1000", "0", "10000", "5"]), "f.gpx")
    assert summary.has_elevation is True
    assert summary.elevation_source == "file"
    assert summary.min_elev_m == -1000.0
    assert summary.max_elev_m == 10000.0
    assert summary.high_point is not None and summary.high_point.elev_m == 10000.0
    assert [p.elev_m for p in summary.points] == [-1000.0, 0.0, 10000.0, 5.0]
    assert summary.gain_m is not None and math.isfinite(summary.gain_m)
    assert summary.loss_m is not None and math.isfinite(summary.loss_m)


def test_just_outside_the_bounds_drops_a_profile_that_was_otherwise_fine() -> None:
    inside = summarise_gpx(doc(["-1000", "10000"]), "f.gpx")
    outside = summarise_gpx(doc(["-1000.001", "10000"]), "f.gpx")
    assert inside.has_elevation is True
    assert outside.has_elevation is False


def test_distance_is_unaffected_by_a_dropped_profile() -> None:
    with_ele = summarise_gpx(doc(["1", "2", "3"]), "f.gpx")
    dropped = summarise_gpx(doc(["1", "1e308", "3"]), "f.gpx")
    assert dropped.distance_m == with_ele.distance_m
    assert [(p.lat, p.lon) for p in dropped.points] == [
        (p.lat, p.lon) for p in with_ele.points
    ]


# --- HTTP ----------------------------------------------------------------------------


@pytest.fixture
def tolerant_client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.mark.parametrize("text", DROPPED)
def test_implausible_elevation_over_http_is_200_with_a_null_profile(
    tolerant_client: TestClient, text: str
) -> None:
    response = tolerant_client.post(
        URL, files={"file": ("f.gpx", doc(["100", text, "150"]), "application/gpx+xml")}
    )
    assert response.status_code == 200, response.text
    summary = RouteSummary.model_validate(response.json())  # finite numbers only
    assert summary.has_elevation is False
    assert all(p.elev_m is None for p in summary.points)
    body = response.json()
    assert body["gain_m"] is None and body["high_point"] is None


@pytest.mark.parametrize(("text", "value"), KEPT)
def test_in_range_elevation_over_http_keeps_the_profile(
    tolerant_client: TestClient, text: str, value: float
) -> None:
    response = tolerant_client.post(
        URL, files={"file": ("f.gpx", doc(["100", text, "50"]), "application/gpx+xml")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_elevation"] is True
    assert response.json()["points"][1]["elev_m"] == value


# --- property: all kept or all nulled -------------------------------------

BOUNDARY_VALUES = [-1000.0, 10000.0, -1000.001, 10000.001, 0.0]


@settings(
    max_examples=150,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    st.lists(
        st.one_of(
            st.floats(allow_nan=True, allow_infinity=True, width=64),
            st.sampled_from(BOUNDARY_VALUES),
        ),
        min_size=2,
        max_size=12,
    )
)
def test_profile_is_present_exactly_when_every_elevation_is_plausible(
    values: list[float],
) -> None:
    summary = summarise_gpx(doc([repr(v) for v in values]), "f.gpx")
    plausible = all(MIN_PLAUSIBLE_ELEV_M <= v <= MAX_PLAUSIBLE_ELEV_M for v in values)
    assert summary.has_elevation is plausible
    if plausible:
        assert summary.min_elev_m == min(values)
        assert summary.max_elev_m == max(values)
    else:
        assert all(p.elev_m is None for p in summary.points)
        assert summary.start.elev_m is None and summary.end.elev_m is None
