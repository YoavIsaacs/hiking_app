"""Every error the app returns has the ErrorResponse shape (ADR 0004 section 2)."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from tests.routes.http_helpers import URL, assert_error


@pytest.fixture
def probe_client(settings: Settings) -> TestClient:
    app: FastAPI = create_app(settings)

    @app.get("/teapot")
    def get_teapot() -> None:
        raise HTTPException(418, "short and stout", headers={"X-Probe": "kept"})

    @app.get("/api-error")
    def raise_api_error() -> None:
        raise ApiError(413, "file_too_large", "custom message")

    @app.get("/typed")
    def get_typed(n: int) -> dict[str, int]:
        return {"n": n}

    return TestClient(app)


def test_unknown_path_is_404_not_found(client: TestClient) -> None:
    assert_error(client.get("/nope"), 404, "not_found")


def test_unknown_path_under_the_routes_prefix_is_404(client: TestClient) -> None:
    assert_error(client.post("/v1/routes/other"), 404, "not_found")


def test_get_on_the_parse_endpoint_is_405_with_allow_post(client: TestClient) -> None:
    response = client.get(URL)
    assert_error(response, 405, "method_not_allowed")
    assert "POST" in response.headers["allow"]


@pytest.mark.parametrize("method", ["put", "delete", "patch"])
def test_other_methods_on_the_parse_endpoint_are_405(
    client: TestClient, method: str
) -> None:
    response = client.request(method, URL)
    assert_error(response, 405, "method_not_allowed")
    assert "POST" in response.headers["allow"]


def test_post_on_health_is_405_with_allow_get(client: TestClient) -> None:
    response = client.post("/health")
    assert_error(response, 405, "method_not_allowed")
    assert "GET" in response.headers["allow"]


def test_any_other_http_exception_is_http_error_and_keeps_its_headers(
    probe_client: TestClient,
) -> None:
    response = probe_client.get("/teapot")
    body = assert_error(response, 418, "http_error")
    assert body["message"] == "short and stout"
    assert response.headers["x-probe"] == "kept"


def test_api_error_uses_its_own_code_and_message(probe_client: TestClient) -> None:
    body = assert_error(probe_client.get("/api-error"), 413, "file_too_large")
    assert body["message"] == "custom message"


def test_validation_error_never_echoes_the_offending_input(
    probe_client: TestClient,
) -> None:
    response = probe_client.get("/typed", params={"n": "SENSITIVE-INPUT-123"})
    body = assert_error(response, 422, "validation_error", detail_is_list=True)
    assert "SENSITIVE-INPUT-123" not in response.text
    detail = body["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"] == ["query", "n"]
    assert set(detail[0]) == {"loc", "msg", "type"}


def test_health_still_works(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
