"""Streaming request-body cap for upload routes (ADR 0004 §3.10)."""

from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any, ClassVar

from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope

from app.routes.params import MAX_UPLOAD_BYTES, MULTIPART_OVERHEAD_BYTES


class BodyLimitRequest(Request):
    def __init__(self, scope: Scope, receive: Receive, *, max_body_bytes: int) -> None:
        super().__init__(scope, receive)
        self.max_body_bytes = max_body_bytes

    async def stream(self) -> AsyncGenerator[bytes, None]:
        """Contract: raises ApiError(413, "file_too_large") past the limit."""
        raise NotImplementedError
        yield b""  # unreachable; makes this an async generator to match the signature


class UploadLimitRoute(APIRoute):
    max_body_bytes: ClassVar[int] = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES

    # Any: FastAPI's signature
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        # Stub: no limit yet (runs at route construction, so it must not raise).
        return super().get_route_handler()
