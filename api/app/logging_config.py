import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

LOGGED_MARK = "_hike_logged"
_HANDLER_MARK = "_hike_json_handler"
_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName", "color_message"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line; always carries the current request ID."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = (
                record.exc_info[0].__name__ if record.exc_info[0] else None
            )
            # Tracebacks stay in server logs; they are never put in responses.
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _SkipAlreadyLogged(logging.Filter):
    """Drop uvicorn's duplicate error line for exceptions the middleware logged."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return not getattr(exc, LOGGED_MARK, False)


def configure_logging(level: str) -> None:
    """Install a single JSON handler on the root logger (idempotent)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel(level)
    # Route uvicorn through the root JSON handler; our middleware logs access lines
    # (uvicorn's own access line is emitted outside the request context).
    for name in ("uvicorn", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True
        uv.filters[:] = [f for f in uv.filters if not isinstance(f, _SkipAlreadyLogged)]
    logging.getLogger("uvicorn.error").addFilter(_SkipAlreadyLogged())
    # httpx logs every request URL at INFO; for the elevation client that is the
    # route's coordinates (user data), so keep its logs to warnings and above.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
