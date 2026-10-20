"""Streaming request-body cap for upload routes (ADR 0004 §3.10)."""

from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any, ClassVar

from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope

from app.errors import ApiError
from app.routes.params import MAX_UPLOAD_BYTES, MULTIPART_OVERHEAD_BYTES


class BodyLimitRequest(Request):
    def __init__(self, scope: Scope, receive: Receive, *, max_body_bytes: int) -> None:
        super().__init__(scope, receive)
        self.max_body_bytes = max_body_bytes

    async def stream(self) -> AsyncGenerator[bytes, None]:
        """Yield the body, raising ApiError(413, "file_too_large") past the limit."""
        total = 0
        async for chunk in super().stream():
            total += len(chunk)
            if total > self.max_body_bytes:
                raise too_large()
            yield chunk


def too_large() -> ApiError:
    return ApiError(
        413,
        "file_too_large",
        f"The upload is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
    )


class UploadLimitRoute(APIRoute):
    max_body_bytes: ClassVar[int] = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:  # Any: FastAPI's signature
        original = super().get_route_handler()
        limit = self.max_body_bytes

        async def handler(request: Request) -> Response:
            declared = request.headers.get("content-length", "")
            # str.isdigit() accepts '²', which int() rejects: such a header is a
            # 400. A value longer than 19 digits is over any limit, and skipping int()
            # keeps huge headers clear of the int/str conversion limit. Anything else
            # non-numeric is left to the streaming cap.
            if declared.isdigit():
                if not declared.isascii():
                    raise ApiError(
                        400, "bad_request", "The Content-Length header is invalid."
                    )
                if len(declared) > 19 or int(declared) > limit:
                    raise too_large()
            limited = BodyLimitRequest(
                request.scope, request.receive, max_body_bytes=limit
            )
            return await original(limited)

        return handler
