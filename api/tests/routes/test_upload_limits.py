"""The three upload-size layers (ADR 0004 3.10): Content-Length pre-check,
streaming cap, exact file length. All before any GPX parsing."""

from fastapi.testclient import TestClient

from app.routes.params import MAX_UPLOAD_BYTES, MULTIPART_OVERHEAD_BYTES
from tests.routes.gpx_builders import gpx_bytes, out_and_back
from tests.routes.http_helpers import (
    URL,
    assert_error,
    multipart_content_type,
    multipart_head,
    multipart_tail,
    padded_to,
    streamed_multipart,
)

MIB = 1024 * 1024
VALID = gpx_bytes([out_and_back()])


def test_limit_is_10_mib() -> None:
    assert MAX_UPLOAD_BYTES == 10 * MIB
    assert MULTIPART_OVERHEAD_BYTES == 64 * 1024


def test_11_mib_file_returns_413_file_too_large(client: TestClient) -> None:
    data = padded_to(VALID, 11 * MIB)
    response = client.post(
        URL, files={"file": ("big.gpx", data, "application/gpx+xml")}
    )
    assert_error(response, 413, "file_too_large")


def test_11_mib_garbage_is_413_not_a_parse_error(client: TestClient) -> None:
    """Size is checked before parsing: unparseable oversize content is still 413."""
    response = client.post(
        URL, files={"file": ("big.gpx", b"\x00" * (11 * MIB), "application/gpx+xml")}
    )
    assert_error(response, 413, "file_too_large")


def test_a_content_length_header_over_the_limit_is_rejected_before_reading(
    client: TestClient,
) -> None:
    """Layer 1: a header promising 50 MiB with a tiny body is refused up front."""
    response = client.post(
        URL,
        content=multipart_head() + VALID + multipart_tail(),
        headers={
            "content-type": multipart_content_type(),
            "content-length": str(50 * MIB),
        },
    )
    assert_error(response, 413, "file_too_large")


def test_chunked_body_without_content_length_over_the_limit_returns_413(
    client: TestClient,
) -> None:
    """Layer 2: no Content-Length at all, the stream is counted."""
    response = client.post(
        URL,
        content=streamed_multipart(12 * MIB),
        headers={"content-type": multipart_content_type()},
    )
    assert_error(response, 413, "file_too_large")


def test_a_lying_small_content_length_does_not_defeat_the_streaming_cap(
    client: TestClient,
) -> None:
    body = multipart_head() + b" " * (12 * MIB) + multipart_tail()
    response = client.post(
        URL,
        content=body,
        headers={"content-type": multipart_content_type(), "content-length": "100"},
    )
    assert_error(response, 413, "file_too_large")


def test_a_valid_chunked_upload_is_accepted(client: TestClient) -> None:
    chunks = [multipart_head(), VALID[:100], VALID[100:], multipart_tail()]
    response = client.post(
        URL, content=iter(chunks), headers={"content-type": multipart_content_type()}
    )
    assert response.status_code == 200, response.text


def test_a_file_of_exactly_10_mib_is_accepted(client: TestClient) -> None:
    data = padded_to(VALID, MAX_UPLOAD_BYTES)
    assert len(data) == MAX_UPLOAD_BYTES
    response = client.post(
        URL, files={"file": ("max.gpx", data, "application/gpx+xml")}
    )
    assert response.status_code == 200, response.text


def test_a_file_one_byte_over_10_mib_is_rejected(client: TestClient) -> None:
    data = padded_to(VALID, MAX_UPLOAD_BYTES + 1)
    response = client.post(
        URL, files={"file": ("max.gpx", data, "application/gpx+xml")}
    )
    assert_error(response, 413, "file_too_large")


def test_exactly_10_mib_is_accepted_on_the_chunked_path_too(client: TestClient) -> None:
    data = padded_to(VALID, MAX_UPLOAD_BYTES)
    chunks = [multipart_head()]
    chunks += [data[i : i + MIB] for i in range(0, len(data), MIB)]
    chunks.append(multipart_tail())
    response = client.post(
        URL, content=iter(chunks), headers={"content-type": multipart_content_type()}
    )
    assert response.status_code == 200, response.text


def test_one_byte_over_10_mib_is_rejected_on_the_chunked_path_too(
    client: TestClient,
) -> None:
    data = padded_to(VALID, MAX_UPLOAD_BYTES + 1)
    chunks = [multipart_head()]
    chunks += [data[i : i + MIB] for i in range(0, len(data), MIB)]
    chunks.append(multipart_tail())
    response = client.post(
        URL, content=iter(chunks), headers={"content-type": multipart_content_type()}
    )
    assert_error(response, 413, "file_too_large")


def test_the_cap_applies_to_the_whole_body_not_just_one_part(
    client: TestClient,
) -> None:
    """Several 6 MiB parts add up past the body cap; none may slip through."""
    parts = [
        ("file", (f"f{i}.gpx", b" " * (6 * MIB), "application/gpx+xml"))
        for i in range(2)
    ]
    response = client.post(URL, files=parts)
    assert_error(response, 413, "file_too_large")


def test_streamed_multipart_helper_totals_the_requested_size() -> None:
    total = sum(len(c) for c in streamed_multipart(3 * MIB, chunk=MIB))
    assert total == len(multipart_head()) + 3 * MIB + len(multipart_tail())
