import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_body
from app.logging_config import LOGGED_MARK, request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_ID = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")

logger = logging.getLogger("app.access")
error_logger = logging.getLogger("app.error")


def resolve_request_id(incoming: str | None) -> str:
    """Use the incoming ID if it is short and safe, otherwise generate one."""
    if incoming is not None and _VALID_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


class RequestIdMiddleware:
    """Pure ASGI middleware: request-ID context var, response header, access log."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            # Log while the request context is still set; ServerErrorMiddleware (outside
            # us) would otherwise log it after the request ID is gone.
            error_logger.exception(
                "unhandled exception",
                extra={"method": scope["method"], "path": scope["path"]},
            )
            setattr(exc, LOGGED_MARK, True)
            if not response_started:
                response = JSONResponse(
                    error_body("internal_error", "Internal Server Error"),
                    status_code=500,
                )
                await response(scope, receive, send_with_id)
            raise
        finally:
            logger.info(
                "request completed",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(token)
