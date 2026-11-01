"""POST /v1/routes/parse through create_app and the real router."""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.middleware import REQUEST_ID_HEADER
from app.models.route import RouteSummary
from app.models.warnings import ELEVATION_UNAVAILABLE
from app.routes.summary import summarise_gpx
from tests.elevation_support import ElevationApi, status_handler
from tests.fixtures.loader import (
    Expected,
    fixture_params,
    invalid_fixtures,
    valid_fixtures,
)
from tests.routes.gpx_builders import Pt, gpx_bytes, out_and_back, straight_line
from tests.routes.http_helpers import URL, assert_error

SECRET = "TOP-SECRET-CONTENT-7f3a9c"


def post(
    client: TestClient,
    data: bytes,
    filename: str = "route.gpx",
    content_type: str = "application/gpx+xml",
) -> httpx.Response:
    response: httpx.Response = client.post(
        URL, files={"file": (filename, data, content_type)}
    )
    return response


# --- 200 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    fixture_params([f for f in valid_fixtures() if f[1].has_elevation]),
)
def test_every_valid_fixture_with_elevation_returns_200_with_a_valid_summary(
    client: TestClient, path: Path, expected: Expected
) -> None:
    response = post(client, path.read_bytes(), path.name)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers[REQUEST_ID_HEADER]
    summary = RouteSummary.model_validate(response.json())
    assert summary == summarise_gpx(path.read_bytes(), path.name)
    assert summary.elevation_source == "file" and summary.warnings == []
    assert set(response.json()) == set(RouteSummary.model_fields)


@pytest.mark.parametrize(
    ("path", "expected"),
    fixture_params([f for f in valid_fixtures() if f[1].has_elevation is False]),
)
def test_every_valid_fixture_without_elevation_is_looked_up_and_returns_200(
    lifespan_client: TestClient, path: Path, expected: Expected
) -> None:
    response = post(lifespan_client, path.read_bytes(), path.name)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers[REQUEST_ID_HEADER]
    summary = RouteSummary.model_validate(response.json())
    assert summary.elevation_source == "lookup" and summary.has_elevation is True
    assert summary.warnings == []
    assert len(summary.points) <= 400
    assert set(response.json()) == set(RouteSummary.model_fields)


def test_nullable_fields_are_present_as_null_not_omitted(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    elevation_api.serve(status_handler(503))  # lookup down: the profile stays null
    data = gpx_bytes([straight_line(5, ele=None)])
    body = post(lifespan_client, data).json()
    for field in ("gain_m", "loss_m", "min_elev_m", "max_elev_m", "high_point"):
        assert field in body and body[field] is None
    assert body["has_elevation"] is False
    assert body["elevation_source"] == "none"
    assert body["warnings"] == [ELEVATION_UNAVAILABLE.model_dump()]


def test_upload_filename_is_used_for_the_name(client: TestClient) -> None:
    body = post(client, gpx_bytes([straight_line(5)]), "Evening_Walk.gpx").json()
    assert body["name"] == "Evening Walk"


def test_content_type_of_the_part_is_not_trusted(client: TestClient) -> None:
    data = gpx_bytes([out_and_back()])
    assert (
        post(client, data, content_type="application/octet-stream").status_code == 200
    )
    assert post(client, data, content_type="text/plain").status_code == 200


def test_extra_form_fields_are_ignored(client: TestClient) -> None:
    response = client.post(
        URL,
        data={"note": "hello"},
        files={"file": ("r.gpx", gpx_bytes([straight_line(5)]), "application/gpx+xml")},
    )
    assert response.status_code == 200


# --- 422 invalid_gpx ---------------------------------------------------------------


@pytest.mark.parametrize(("path", "expected"), fixture_params(invalid_fixtures()))
def test_invalid_fixtures_return_422_with_the_expected_code(
    client: TestClient, path: Path, expected: Expected
) -> None:
    assert expected.expected_error is not None
    assert_error(
        post(client, path.read_bytes(), path.name), 422, expected.expected_error
    )


def test_malformed_xml_returns_422_invalid_gpx(client: TestClient) -> None:
    assert_error(post(client, b'<gpx><trk><trkseg><trkpt lat="1'), 422, "invalid_gpx")


def test_kml_returns_422_invalid_gpx(client: TestClient) -> None:
    kml = b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'
    assert_error(post(client, kml), 422, "invalid_gpx")


def test_empty_file_returns_422_invalid_gpx(client: TestClient) -> None:
    assert_error(post(client, b""), 422, "invalid_gpx")


def test_non_utf8_file_returns_422_invalid_gpx(client: TestClient) -> None:
    data = gpx_bytes([straight_line(3)], metadata_name="x").replace(b"x", b"\xe9")
    assert_error(post(client, data), 422, "invalid_gpx")


def test_binary_garbage_returns_422_invalid_gpx(client: TestClient) -> None:
    assert_error(post(client, bytes(range(256)) * 40), 422, "invalid_gpx")


@pytest.mark.parametrize("bad", ["91", "-91", "NaN", "abc"])
def test_out_of_range_or_non_finite_latitude_returns_422_invalid_gpx(
    client: TestClient, bad: str
) -> None:
    data = (
        '<gpx version="1.1" creator="t"><trk><trkseg><trkpt lat="1" lon="1"/>'
        f'<trkpt lat="{bad}" lon="1"/></trkseg></trk></gpx>'
    ).encode()
    assert_error(post(client, data), 422, "invalid_gpx")


def test_xxe_payload_returns_422_and_never_echoes_the_file(
    client: TestClient, tmp_path: Path
) -> None:
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text(SECRET, encoding="utf-8")
    payload = (
        '<?xml version="1.0"?>'
        f'<!DOCTYPE gpx [<!ENTITY x SYSTEM "{secret_file.as_uri()}">]>'
        '<gpx version="1.1" creator="t"><metadata><name>&x;</name></metadata>'
        "<trk><trkseg>"
        '<trkpt lat="1" lon="1"/><trkpt lat="1.001" lon="1"/></trkseg></trk></gpx>'
    ).encode()
    response = post(client, payload)
    assert_error(response, 422, "invalid_gpx")
    assert SECRET not in response.text


def test_billion_laughs_payload_returns_422_quickly(client: TestClient) -> None:
    entities = '<!ENTITY a0 "lol">' + "".join(
        f'<!ENTITY a{i} "{f"&a{i - 1};" * 10}">' for i in range(1, 10)
    )
    payload = (
        f'<?xml version="1.0"?><!DOCTYPE gpx [{entities}]>'
        '<gpx version="1.1" creator="t">'
        "<metadata><name>&a9;</name></metadata></gpx>"
    ).encode()
    assert_error(post(client, payload), 422, "invalid_gpx")


# --- 422 too_few_points --------------------------------------------------------------


def test_one_point_file_returns_422_too_few_points(client: TestClient) -> None:
    assert_error(post(client, gpx_bytes([straight_line(1)])), 422, "too_few_points")


def test_two_identical_points_return_422_too_few_points(client: TestClient) -> None:
    p = Pt(31.9, 34.9, 10.0)
    assert_error(post(client, gpx_bytes([[p, p]])), 422, "too_few_points")


def test_waypoint_only_file_returns_422_too_few_points(client: TestClient) -> None:
    data = (
        b'<gpx version="1.1" creator="t">'
        b'<wpt lat="1" lon="1"/><wpt lat="2" lon="2"/></gpx>'
    )
    assert_error(post(client, data), 422, "too_few_points")


# --- 422 validation_error ------------------------------------------------------------


def _assert_validation_error(response: httpx.Response, echoed: str = "") -> None:
    body = assert_error(response, 422, "validation_error", detail_is_list=True)
    detail = body["detail"]
    assert isinstance(detail, list) and detail
    for item in detail:
        assert set(item) == {"loc", "msg", "type"}, "input/ctx/url must be dropped"
    if echoed:
        assert echoed not in response.text


def test_missing_file_field_returns_422_validation_error(client: TestClient) -> None:
    response = client.post(URL, files={"other": (None, "value")})
    _assert_validation_error(response)
    assert response.json()["detail"][0]["loc"] == ["body", "file"]


def test_file_sent_as_a_text_field_returns_422_validation_error(
    client: TestClient,
) -> None:
    response = client.post(URL, files={"file": (None, "SENSITIVE-INPUT-123")})
    _assert_validation_error(response, "SENSITIVE-INPUT-123")
    assert response.json()["detail"][0]["loc"] == ["body", "file"]


def test_json_body_returns_422_validation_error_without_echo(
    client: TestClient,
) -> None:
    response = client.post(URL, json={"file": "SENSITIVE-INPUT-123"})
    _assert_validation_error(response, "SENSITIVE-INPUT-123")


def test_empty_request_body_returns_422_validation_error(client: TestClient) -> None:
    _assert_validation_error(client.post(URL))


# --- 400 bad_request -----------------------------------------------------------------


def test_malformed_multipart_returns_400_bad_request(client: TestClient) -> None:
    response = client.post(
        URL,
        content=b"this is not multipart at all",
        headers={"content-type": "multipart/form-data; boundary=zzz"},
    )
    assert_error(response, 400, "bad_request")


def test_multipart_without_a_boundary_returns_400_bad_request(
    client: TestClient,
) -> None:
    response = client.post(
        URL, content=b"x", headers={"content-type": "multipart/form-data"}
    )
    assert_error(response, 400, "bad_request")


# --- request ID ------------------------------------------------------------


def test_incoming_request_id_is_echoed_on_a_422(client: TestClient) -> None:
    response = client.post(
        URL,
        files={"file": ("r.gpx", b"", "application/gpx+xml")},
        headers={REQUEST_ID_HEADER: "qa-req-1"},
    )
    assert_error(response, 422, "invalid_gpx")
    assert response.headers[REQUEST_ID_HEADER] == "qa-req-1"


def test_request_id_is_present_on_a_200(client: TestClient) -> None:
    response = post(client, gpx_bytes([straight_line(5)]))
    assert response.status_code == 200
    assert len(response.headers[REQUEST_ID_HEADER]) == 32
