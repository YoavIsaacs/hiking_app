"""Operation-ID generation and validation (ADR 0001, decision 1)."""

import re
from collections import Counter

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

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


def _api_route_contexts(app: FastAPI) -> list[tuple[APIRoute, str]]:
    """Return every served APIRoute with its effective unique ID.

    FastAPI 0.143 keeps included routers as a single placeholder in ``app.routes``;
    ``iter_route_contexts`` (public) expands them with the include context applied
    (prefix, generate_unique_id_function), so the unique ID is the effective one.
    """
    found: list[tuple[APIRoute, str]] = []
    for context in iter_route_contexts(app.routes):
        original = context.original_route
        if isinstance(original, APIRoute):
            unique_id: str = context.unique_id
            found.append((original, unique_id))
    return found


def check_operation_ids(app: FastAPI) -> None:
    """Fail loudly if any operation ID in the app is not camelCase or not unique."""
    routes = _api_route_contexts(app)
    for route, unique_id in routes:
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
        if unique_id != operation_id(route):
            raise OperationIdError(
                f"route {route.path!r} was not built with generate_unique_id_function="
                "operation_id"
            )
    counts = Counter(unique_id for _, unique_id in routes)
    duplicates = sorted(i for i, n in counts.items() if n > 1)
    if duplicates:
        raise OperationIdError(f"duplicate operation IDs: {', '.join(duplicates)}")
