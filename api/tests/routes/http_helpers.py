"""Shared HTTP helpers for the endpoint tests."""

from collections.abc import Iterator

import httpx

from app.middleware import REQUEST_ID_HEADER

URL = "/v1/routes/parse"
BOUNDARY = "qa-boundary-7d1c"


def assert_error(
    response: httpx.Response, status: int, code: str, *, detail_is_list: bool = False
) -> dict[str, object]:
    """The ErrorResponse shape: exactly code/message/detail, plus a request ID."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"code", "message", "detail"}, body
    assert body["code"] == code, body
    assert isinstance(body["message"], str) and body["message"]
    assert (isinstance(body["detail"], list)) == detail_is_list, body
    assert response.headers[REQUEST_ID_HEADER]
    assert isinstance(body, dict)
    return body


def multipart_head(filename: str = "r.gpx") -> bytes:
    return (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/gpx+xml\r\n\r\n"
    ).encode()


def multipart_tail() -> bytes:
    return f"\r\n--{BOUNDARY}--\r\n".encode()


def multipart_content_type() -> str:
    return f"multipart/form-data; boundary={BOUNDARY}"


def streamed_multipart(file_bytes: int, *, chunk: int = 1024 * 1024) -> Iterator[bytes]:
    """A generator body (so httpx sends it chunked, with no Content-Length) holding a
    ``file`` part of ``file_bytes`` bytes. The content is padding, never valid GPX."""
    yield multipart_head()
    remaining = file_bytes
    while remaining > 0:
        n = min(chunk, remaining)
        yield b" " * n
        remaining -= n
    yield multipart_tail()


def padded_to(gpx: bytes, total: int) -> bytes:
    """``gpx`` plus trailing whitespace (legal after the root) up to ``total`` bytes."""
    assert len(gpx) <= total
    return gpx + b" " * (total - len(gpx))
