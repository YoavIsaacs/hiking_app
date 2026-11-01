"""Every non-200 shape of POST /v1/routes/parse as ready-to-send multipart bodies.

Pure builders (standard library and ``tests.routes`` helpers only), so they run inside
the production image, which has no pytest. Used by ``test_reject_paths_hold_nothing.py``
(in-process) and by ``rss_probe --shape`` (over HTTP, in the image).
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.routes.params import MAX_UPLOAD_BYTES
from tests.routes.gpx_builders import gpx_bytes, out_and_back, straight_line
from tests.routes.http_helpers import (
    BOUNDARY,
    multipart_content_type,
    multipart_head,
    multipart_tail,
    padded_to,
)

MIB = 1024 * 1024
UPLOAD = 6 * MIB  # big enough that a held copy is unmistakable
POINT = b'<trkpt lat="1" lon="1"/>'
NS_URI = "urn:" + "u" * 253  # 257 characters: one over the cap


def gpx(body: bytes) -> bytes:
    return b"<gpx><trk><trkseg>" + body + b"</trkseg></trk></gpx>"


def multipart(data: bytes, *, field: str = "file") -> bytes:
    head = multipart_head().replace(b'name="file"', f'name="{field}"'.encode())
    return head + data + multipart_tail()


@dataclass(frozen=True)
class Shape:
    """One request: its body, content type, and the status/code it must get."""

    body: bytes
    status: int
    code: str | None = None  # the ErrorResponse code; None for a 200
    content_type: str = ""
    chunked: bool = False  # sent with Transfer-Encoding: chunked, no Content-Length

    @property
    def headers_content_type(self) -> str:
        return self.content_type or multipart_content_type()


def _reject(data: bytes, code: str) -> Shape:
    return Shape(multipart(data), 422, code)


def rejects() -> dict[str, Shape]:
    """422 from the GPX pipeline (RouteParseError)."""
    return {
        "too_many_points": _reject(gpx(POINT * 100_001), "too_many_points"),
        "too_few_points": _reject(padded_to(gpx(POINT * 2), UPLOAD), "too_few_points"),
        "namespace_uri_over_cap": _reject(
            padded_to(f'<gpx xmlns="{NS_URI}"/>'.encode(), UPLOAD), "invalid_gpx"
        ),
        "prefixed_namespace_uri_over_cap": _reject(
            padded_to(f'<gpx xmlns:a="{NS_URI}"/>'.encode(), UPLOAD), "invalid_gpx"
        ),
        "nested_too_deeply": _reject(
            padded_to(b"<gpx>" + b"<a>" * 200 + b"</a>" * 200 + b"</gpx>", UPLOAD),
            "invalid_gpx",
        ),
        "kml_not_gpx": _reject(
            padded_to(b"<kml><Document/></kml>", UPLOAD), "invalid_gpx"
        ),
        "empty_file": _reject(b"", "invalid_gpx"),
        "whitespace_only": _reject(b" " * UPLOAD, "invalid_gpx"),
        "not_utf8": _reject(
            padded_to(b"<gpx>\xff\xfe\x00</gpx>", UPLOAD), "invalid_gpx"
        ),
        "unsupported_encoding": _reject(
            padded_to(b'<?xml version="1.0" encoding="x-nope"?><gpx/>', UPLOAD),
            "invalid_gpx",
        ),
        "dtd": _reject(
            padded_to(b'<!DOCTYPE gpx [<!ENTITY a "b">]><gpx/>', UPLOAD),
            "invalid_gpx",
        ),
        "truncated": _reject(
            b"<gpx><trk><trkseg>" + POINT * 10 + b" " * UPLOAD, "invalid_gpx"
        ),
        "text_flood_in_unclosed_name": _reject(
            b"<gpx><name>" + b"x" * 4 * MIB, "invalid_gpx"
        ),
    }


def too_large() -> dict[str, Shape]:
    """413, the three ways to get there."""
    over = padded_to(gpx(POINT * 2), MAX_UPLOAD_BYTES + 1)
    long_body = multipart(padded_to(gpx(POINT * 2), MAX_UPLOAD_BYTES + 200_000))
    return {
        "413_file_one_byte_over_10MB": Shape(multipart(over), 413, "file_too_large"),
        "413_content_length_over_limit": Shape(long_body, 413, "file_too_large"),
        "413_chunked_body_over_limit": Shape(
            long_body, 413, "file_too_large", chunked=True
        ),
    }


def validation() -> dict[str, Shape]:
    """422 validation_error (no usable ``file`` part); one 400 from the form parser."""
    data = padded_to(gpx(POINT * 2), UPLOAD)
    plain_text = (
        (
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"\r\n\r\n'
        ).encode()
        + data
        + multipart_tail()
    )
    return {
        "validation_wrong_field_name": Shape(
            multipart(data, field="x"), 422, "validation_error"
        ),
        "validation_not_multipart": Shape(
            data, 422, "validation_error", content_type="application/json"
        ),
        # a `file` part without a filename is a form field: Starlette caps it at 1 MiB
        "bad_request_file_part_is_plain_text": Shape(plain_text, 400, "bad_request"),
        "validation_empty_body": Shape(b"", 422, "validation_error"),
    }


def accepted() -> dict[str, Shape]:
    """200s: the lookup-failure shape needs Open-Meteo to fail (a closed port does)."""
    no_ele = gpx_bytes([straight_line(120, step_m=135.0, ele=None)])
    return {
        "200_no_elevation_big": Shape(multipart(padded_to(no_ele, UPLOAD)), 200),
        "200_valid_big": Shape(
            multipart(padded_to(gpx_bytes([out_and_back()]), UPLOAD)), 200
        ),
    }


SHAPE_GROUPS: dict[str, Callable[[], dict[str, Shape]]] = {
    "rejects": rejects,
    "too_large": too_large,
    "validation": validation,
    "accepted": accepted,
}


def all_shapes() -> dict[str, Shape]:
    out: dict[str, Shape] = {}
    for group in SHAPE_GROUPS.values():
        out |= group()
    return out
