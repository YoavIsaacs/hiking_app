"""Operation-ID generation and validation (ADR 0001, decision 1)."""

import re
from collections import Counter

from fastapi import FastAPI
from fastapi.routing import APIRoute

_HANDLER_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


class OperationIdError(RuntimeError):
    """Raised when an operation ID is missing, malformed or duplicated."""


def operation_id(route: APIRoute) -> str:
    """Return the clean camelCase operation ID for a route."""
    handler = route.endpoint.__name__
    if not _HANDLER_NAME.fullmatch(handler):
        raise OperationIdError(
            f"handler name {handler!r} must be verb_noun snake_case "
            "(lowercase words joined by single underscores, at least two words)"
        )
    methods = route.methods or set()
    if len(methods) != 1:
        raise OperationIdError(
            f"route {route.path!r} ({handler}) must have exactly one HTTP method, "
            f"got {sorted(methods)}"
        )
    first, *rest = handler.split("_")
    return first + "".join(word.capitalize() for word in rest)


def check_operation_ids(app: FastAPI) -> None:
    """Fail loudly if any operation ID in the app is not camelCase or not unique."""
    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    for route in routes:
        handler = route.endpoint.__name__
        if route.operation_id is not None:
            raise OperationIdError(
                f"route {route.path!r} sets operation_id by hand; "
                "IDs come from the handler name"
            )
        if route.name != handler:
            raise OperationIdError(
                f"route {route.path!r} sets name={route.name!r} differing from "
                f"handler name {handler!r}; remove the name override"
            )
        if route.unique_id != operation_id(route):
            raise OperationIdError(
                f"route {route.path!r} was not built with generate_unique_id_function="
                "operation_id"
            )
    counts = Counter(r.unique_id for r in routes)
    duplicates = sorted(i for i, n in counts.items() if n > 1)
    if duplicates:
        raise OperationIdError(f"duplicate operation IDs: {', '.join(duplicates)}")
