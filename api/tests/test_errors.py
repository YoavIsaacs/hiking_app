import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.middleware import REQUEST_ID_HEADER


def _app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret detail")

    return app


def _lines(text: str) -> list[dict[str, object]]:
    return [json.loads(ln) for ln in text.splitlines() if ln[:1] == "{"]


def test_unhandled_error_is_generic_500_with_request_id(settings: Settings) -> None:
    client = TestClient(_app(settings), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert "secret detail" not in response.text
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


def test_unhandled_error_honours_incoming_request_id(settings: Settings) -> None:
    client = TestClient(_app(settings), raise_server_exceptions=False)
    response = client.get("/boom", headers={REQUEST_ID_HEADER: "err-1"})
    assert response.headers[REQUEST_ID_HEADER] == "err-1"


def test_unhandled_error_logged_with_request_id_and_traceback(
    capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    client = TestClient(_app(settings), raise_server_exceptions=False)
    response = client.get("/boom", headers={REQUEST_ID_HEADER: "err-2"})
    lines = _lines(capsys.readouterr().err)
    errors = [d for d in lines if d["level"] == "ERROR"]
    assert len(errors) == 1
    assert errors[0]["request_id"] == response.headers[REQUEST_ID_HEADER] == "err-2"
    assert errors[0]["path"] == "/boom"
    assert "RuntimeError: secret detail" in str(errors[0]["exc_info"])
    access = next(d for d in lines if d["logger"] == "app.access")
    assert access["status"] == 500
    assert access["request_id"] == "err-2"


def test_error_still_propagates_to_the_server(settings: Settings) -> None:
    with pytest.raises(RuntimeError):
        TestClient(_app(settings)).get("/boom")
