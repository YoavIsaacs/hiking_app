"""Unit tests for app.errors and app.body_limit internals."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message, Scope

from app.body_limit import BodyLimitRequest, UploadLimitRoute, too_large
from app.config import Settings
from app.errors import ApiError, error_body
from app.main import create_app
from app.models.errors import ErrorResponse, FieldError
from app.routes.params import MAX_UPLOAD_BYTES, MULTIPART_OVERHEAD_BYTES


def test_error_body_is_an_error_response_dump() -> None:
    body = error_body("invalid_gpx", "bad")
    assert body == {"code": "invalid_gpx", "message": "bad", "detail": None}
    assert ErrorResponse.model_validate(body).code == "invalid_gpx"


def test_error_body_carries_field_errors() -> None:
    detail = [FieldError(loc=["body", "file", 0], msg="m", type="t")]
    body = error_body("validation_error", "x", detail)
    assert body["detail"] == [{"loc": ["body", "file", 0], "msg": "m", "type": "t"}]


def test_api_error_is_an_http_exception_with_a_code() -> None:
    exc = ApiError(413, "file_too_large", "big")
    assert isinstance(exc, StarletteHTTPException)
    assert (exc.status_code, exc.code, exc.detail) == (413, "file_too_large", "big")


@pytest.fixture
def probe(settings: Settings) -> TestClient:
    app: FastAPI = create_app(settings)

    @app.get("/unauthorised")
    def get_unauthorised() -> None:
        raise HTTPException(401, "nope")

    @app.get("/dict-detail")
    def get_dict_detail() -> None:
        raise HTTPException(409, {"a": 1})

    @app.get("/many")
    def get_many(a: int, b: int) -> dict[str, int]:
        return {"a": a, "b": b}

    return TestClient(app)


def test_other_4xx_statuses_map_to_http_error(probe: TestClient) -> None:
    response = probe.get("/unauthorised")
    assert response.status_code == 401
    assert response.json() == {"code": "http_error", "message": "nope", "detail": None}


def test_non_string_details_are_stringified(probe: TestClient) -> None:
    response = probe.get("/dict-detail")
    assert response.json()["message"] == "{'a': 1}"


def test_every_validation_error_is_reported_without_input(probe: TestClient) -> None:
    response = probe.get("/many", params={"a": "x", "b": "y"})
    detail = response.json()["detail"]
    assert [d["loc"] for d in detail] == [["query", "a"], ["query", "b"]]
    assert all(set(d) == {"loc", "msg", "type"} for d in detail)


# --- body limit -----------------------------------------------------------------------


def _request(chunks: list[bytes], limit: int) -> BodyLimitRequest:
    messages: list[Message] = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]

    async def receive() -> Message:
        return messages.pop(0)

    scope: Scope = {"type": "http", "headers": []}
    return BodyLimitRequest(scope, receive, max_body_bytes=limit)


async def _drain(stream: AsyncIterator[bytes]) -> list[bytes]:
    return [c async for c in stream]


@pytest.mark.anyio
async def test_stream_passes_a_body_exactly_at_the_limit() -> None:
    chunks = await _drain(_request([b"abc", b"de"], 5).stream())
    assert b"".join(chunks) == b"abcde"


@pytest.mark.anyio
async def test_stream_raises_413_one_byte_over_the_limit() -> None:
    with pytest.raises(ApiError) as excinfo:
        await _drain(_request([b"abc", b"def"], 5).stream())
    assert excinfo.value.status_code == 413
    assert excinfo.value.code == "file_too_large"


def test_too_large_message_names_the_limit() -> None:
    assert "10 MB" in str(too_large().detail)


def test_the_route_limit_is_the_upload_limit_plus_multipart_overhead() -> None:
    assert (
        UploadLimitRoute.max_body_bytes == MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES
    )


def test_a_garbage_body_with_a_small_content_length_still_gets_an_error_shape(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/routes/parse",
        content=b"x",
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert response.status_code in {400, 422}
    assert set(response.json()) == {"code", "message", "detail"}
