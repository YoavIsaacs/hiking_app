"""API error type, handlers and OpenAPI error responses (ADR 0004 §2)."""

from typing import Any, Final

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.models.errors import ErrorCode, ErrorResponse, FieldError


class ApiError(StarletteHTTPException):
    """Starlette's HTTPException so FastAPI's body reader re-raises it unchanged."""

    code: ErrorCode

    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code


def error_body(
    code: ErrorCode, message: str, detail: list[FieldError] | None = None
) -> dict[str, object]:
    raise NotImplementedError


def install_error_handlers(app: FastAPI) -> None:
    """Contract: StarletteHTTPException + RequestValidationError -> ErrorResponse.

    Stub: registers nothing, so the default FastAPI error bodies stay in place.
    """
    return


# Any: FastAPI's `responses=` parameter type
ERROR_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    400: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}
