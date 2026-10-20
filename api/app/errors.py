"""API error type, handlers and OpenAPI error responses (ADR 0004 §2)."""

from typing import Any, Final, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

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
    """The JSON body of every error response."""
    return ErrorResponse(code=code, message=message, detail=detail).model_dump(
        mode="json"
    )


_STATUS_CODES: Final[dict[int, ErrorCode]] = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
}


def _code_for(exc: StarletteHTTPException) -> ErrorCode:
    if isinstance(exc, ApiError):
        return exc.code
    return _STATUS_CODES.get(exc.status_code, "http_error")


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    http_exc = cast(StarletteHTTPException, exc)
    return JSONResponse(
        error_body(_code_for(http_exc), str(http_exc.detail)),
        status_code=http_exc.status_code,
        headers=http_exc.headers,
    )


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    # input, ctx and url are dropped so uploaded content is never echoed back.
    errors = cast(RequestValidationError, exc).errors()
    detail = [
        FieldError(loc=list(e["loc"]), msg=e["msg"], type=e["type"]) for e in errors
    ]
    return JSONResponse(
        error_body("validation_error", "The request is invalid.", detail),
        status_code=422,
    )


def install_error_handlers(app: FastAPI) -> None:
    """StarletteHTTPException + RequestValidationError -> ErrorResponse."""
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)


ERROR_RESPONSES: Final[
    dict[int | str, dict[str, Any]]  # Any: FastAPI's `responses=` parameter type
] = {
    400: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}
