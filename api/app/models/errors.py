"""Error contract shared by every endpoint (ADR 0004 §2)."""

from typing import Literal

from pydantic import BaseModel

ErrorCode = Literal[
    "bad_request",
    "not_found",
    "method_not_allowed",
    "file_too_large",
    "invalid_gpx",
    "too_few_points",
    "validation_error",
    "http_error",
    "internal_error",
]


class FieldError(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    detail: list[FieldError] | None
