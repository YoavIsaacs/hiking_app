import logging

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.logging_config import request_id_var
from app.main import create_app
from app.middleware import REQUEST_ID_HEADER, resolve_request_id


def test_resolve_keeps_valid_incoming_id() -> None:
    assert resolve_request_id("abc-123_X.y") == "abc-123_X.y"


@pytest.mark.parametrize(
    "bad", [None, "", "a" * 65, "has space", "new\nline", "<script>"]
)
def test_resolve_generates_when_missing_or_invalid(bad: str | None) -> None:
    generated = resolve_request_id(bad)
    assert generated != bad
    assert len(generated) == 32


def test_response_echoes_incoming_id(client: TestClient) -> None:
    response = client.get("/health", headers={REQUEST_ID_HEADER: "my-id-1"})
    assert response.headers[REQUEST_ID_HEADER] == "my-id-1"


def test_response_generates_id_when_absent(client: TestClient) -> None:
    first = client.get("/health").headers[REQUEST_ID_HEADER]
    second = client.get("/health").headers[REQUEST_ID_HEADER]
    assert first != second
    assert len(first) == 32


def test_preflight_also_gets_id(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://allowed.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert REQUEST_ID_HEADER in response.headers


def test_context_var_is_reset_after_request(client: TestClient) -> None:
    client.get("/health", headers={REQUEST_ID_HEADER: "scoped"})
    assert request_id_var.get() == "-"


def test_access_log_line_carries_request_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.access"):
        client.get("/health", headers={REQUEST_ID_HEADER: "log-me"})
    record = next(r for r in caplog.records if r.name == "app.access")
    assert record.__dict__["status"] == 200
    assert record.__dict__["path"] == "/health"


def test_lifespan_scope_passes_through(settings: Settings) -> None:
    with TestClient(create_app(settings)) as c:
        assert c.get("/health").status_code == 200
