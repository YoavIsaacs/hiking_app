"""Operation-ID generation and validation (ADR 0001, decision 2)."""

from fastapi import FastAPI
from fastapi.routing import APIRoute


class OperationIdError(RuntimeError):
    """Raised when an operation ID is missing, malformed or duplicated."""


def operation_id(route: APIRoute) -> str:
    """Return the clean camelCase operation ID for a route."""
    raise NotImplementedError


def check_operation_ids(app: FastAPI) -> None:
    """Fail loudly if any operation ID in the app is not camelCase or not unique."""
    raise NotImplementedError
