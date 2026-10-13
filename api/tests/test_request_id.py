import json

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
    capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    client = TestClient(create_app(settings))
    client.get("/health", headers={REQUEST_ID_HEADER: "log-me"})
    lines = [
        json.loads(ln) for ln in capsys.readouterr().err.splitlines() if ln[:1] == "{"
    ]
    access = next(d for d in lines if d["logger"] == "app.access")
    assert access["request_id"] == "log-me"
    assert access["status"] == 200
    assert access["path"] == "/health"


def test_lifespan_scope_passes_through(settings: Settings) -> None:
    with TestClient(create_app(settings)) as c:
        assert c.get("/health").status_code == 200
