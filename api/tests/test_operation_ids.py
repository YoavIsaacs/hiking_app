"""ADR 0001 decision 1: operation IDs are clean camelCase and unique."""

import re
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from app.config import Settings
from app.main import create_app
from app.operation_ids import OperationIdError, check_operation_ids, operation_id

CAMEL_CASE = r"^[a-z][a-zA-Z0-9]*$"


def _route(endpoint: Callable[..., Any], methods: list[str] | None = None) -> APIRoute:
    return APIRoute("/x", endpoint, methods=methods or ["GET"])


def _named(name: str) -> Callable[[], None]:
    def endpoint() -> None:
        return None

    endpoint.__name__ = name
    return endpoint


def _clean_app() -> FastAPI:
    app = FastAPI(generate_unique_id_function=operation_id)

    @app.get("/routes")
    def get_routes() -> dict[str, str]:
        return {}

    @app.post("/checklists")
    def create_checklist() -> dict[str, str]:
        return {}

    return app


@pytest.mark.parametrize(
    ("handler_name", "expected"),
    [
        ("parse_route", "parseRoute"),
        ("create_checklist", "createChecklist"),
        ("get_health", "getHealth"),
        ("get_weather_forecast", "getWeatherForecast"),
        ("get_route2", "getRoute2"),
        ("list_v2_items", "listV2Items"),
    ],
)
def test_operation_id_converts_snake_case_handler_to_camel_case(
    handler_name: str, expected: str
) -> None:
    assert operation_id(_route(_named(handler_name))) == expected


@pytest.mark.parametrize(
    "bad_name",
    [
        "health",  # single word
        "_get_health",  # leading underscore
        "get_health_",  # trailing underscore
        "get__health",  # double underscore
        "Get_health",  # uppercase first
        "get_Health",  # uppercase later
        "getHealth",  # already camelCase
        "1_get_health",  # digit first
        "get-health",  # hyphen
        "",  # empty
    ],
)
def test_operation_id_rejects_names_that_are_not_verb_noun_snake_case(
    bad_name: str,
) -> None:
    with pytest.raises(OperationIdError):
        operation_id(_route(_named(bad_name)))


def test_operation_id_rejects_route_with_more_than_one_method() -> None:
    with pytest.raises(OperationIdError):
        operation_id(_route(_named("get_thing"), methods=["GET", "POST"]))


def test_operation_id_ignores_a_name_override_and_uses_the_handler_name() -> None:
    route = APIRoute("/x", _named("get_thing"), methods=["GET"], name="something_else")
    assert operation_id(route) == "getThing"


def test_check_operation_ids_passes_for_a_clean_app() -> None:
    check_operation_ids(_clean_app())


def test_check_operation_ids_passes_for_an_app_with_no_routes() -> None:
    check_operation_ids(FastAPI(generate_unique_id_function=operation_id))


def test_check_operation_ids_raises_on_same_handler_name_on_two_paths() -> None:
    app = FastAPI(generate_unique_id_function=operation_id)

    def get_thing() -> dict[str, str]:
        return {}

    app.add_api_route("/a", get_thing, methods=["GET"])
    app.add_api_route("/b", get_thing, methods=["GET"])
    with pytest.raises(OperationIdError, match="getThing"):
        check_operation_ids(app)


def test_check_operation_ids_raises_on_hand_set_operation_id() -> None:
    app = FastAPI(generate_unique_id_function=operation_id)

    @app.get("/a", operation_id="customName")
    def get_thing() -> dict[str, str]:
        return {}

    with pytest.raises(OperationIdError, match="operation_id"):
        check_operation_ids(app)


def test_check_operation_ids_raises_when_name_differs_from_handler_name() -> None:
    app = FastAPI(generate_unique_id_function=operation_id)

    @app.get("/a", name="other_name")
    def get_thing() -> dict[str, str]:
        return {}

    with pytest.raises(OperationIdError, match="name"):
        check_operation_ids(app)


def test_check_operation_ids_raises_when_app_uses_fastapi_default_ids() -> None:
    app = FastAPI()

    @app.get("/a")
    def get_thing() -> dict[str, str]:
        return {}

    with pytest.raises(OperationIdError):
        check_operation_ids(app)


def test_every_operation_in_the_real_app_schema_is_camel_case_and_unique(
    settings: Settings,
) -> None:
    schema = create_app(settings).openapi()
    ids = [
        op["operationId"]
        for path_item in schema["paths"].values()
        for op in path_item.values()
    ]
    assert ids, "the real app exposes no operations"
    assert all(re.fullmatch(CAMEL_CASE, i) for i in ids), ids
    assert len(ids) == len(set(ids))


def test_health_get_operation_id_is_get_health(settings: Settings) -> None:
    schema = create_app(settings).openapi()
    assert schema["paths"]["/health"]["get"]["operationId"] == "getHealth"


def _app_with_extra_route(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, **route_kwargs: Any
) -> None:
    """Make create_app include an extra route, via the module it really includes."""
    from app.routers import health

    extra = APIRouter()

    def get_thing() -> dict[str, str]:
        return {}

    extra.add_api_route("/thing", get_thing, methods=["GET"], **route_kwargs)
    extra.include_router(health.router)
    monkeypatch.setattr(health, "router", extra)


def test_create_app_rejects_a_route_with_a_hand_set_operation_id(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _app_with_extra_route(monkeypatch, settings, operation_id="getThing")
    with pytest.raises(OperationIdError, match="operation_id"):
        create_app(settings)


def test_create_app_rejects_a_route_with_a_name_override(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _app_with_extra_route(monkeypatch, settings, name="other_name")
    with pytest.raises(OperationIdError, match="name"):
        create_app(settings)


def test_every_route_in_the_real_app_uses_the_generated_operation_id(
    settings: Settings,
) -> None:
    routes = [r for r in create_app(settings).routes if isinstance(r, APIRoute)]
    assert routes, "the real app exposes no API routes"
    for route in routes:
        assert route.operation_id is None, route.path
        assert route.unique_id == operation_id(route), route.path
