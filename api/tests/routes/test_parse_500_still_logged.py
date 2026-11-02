"""The traceback-cycle fix only scrubs RouteParseError (a 422). A bug in the worker
(any other exception) is still a 500 that logs its traceback with the request ID
(ADR 0004 item 56: "behaviour unchanged"), through the real app and route."""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.middleware import REQUEST_ID_HEADER
from tests.routes.http_helpers import (
    URL,
    multipart_content_type,
    multipart_head,
    multipart_tail,
)


def test_an_unexpected_worker_error_is_a_500_with_its_traceback_logged(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("worker bug 8841")

    monkeypatch.setattr("app.services.route_parse.summarise_gpx", boom)
    body = multipart_head() + b"<gpx/>" + multipart_tail()
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.post(
            URL,
            content=body,
            headers={
                "Content-Type": multipart_content_type(),
                REQUEST_ID_HEADER: "req-8841",
            },
        )
    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "req-8841"
    assert "worker bug 8841" not in response.text  # nothing internal in the body
    lines = [
        json.loads(ln) for ln in capsys.readouterr().err.splitlines() if ln[:1] == "{"
    ]
    errors = [d for d in lines if d["level"] == "ERROR"]
    assert len(errors) == 1
    assert errors[0]["request_id"] == "req-8841"
    trace = str(errors[0]["exc_info"])
    assert "RuntimeError: worker bug 8841" in trace
    assert "summarise_in_worker" in trace  # the traceback still names the worker frame
