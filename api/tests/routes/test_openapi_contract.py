"""The OpenAPI document of POST /v1/routes/parse (ADR 0004 section 2, "Contract")."""

from typing import Any

import pytest

from app.config import Settings
from app.main import create_app

# Any: parsed OpenAPI JSON is untyped
Schema = dict[str, Any]


@pytest.fixture
def spec(settings: Settings) -> Schema:
    return create_app(settings).openapi()


def _ref(response: Schema) -> str:
    return str(response["content"]["application/json"]["schema"]["$ref"])


def test_parse_route_operation_exists_with_the_expected_id(spec: Schema) -> None:
    operation = spec["paths"]["/v1/routes/parse"]["post"]
    assert operation["operationId"] == "parseRoute"
    assert set(spec["paths"]["/v1/routes/parse"]) == {"post"}


def test_200_is_route_summary(spec: Schema) -> None:
    responses = spec["paths"]["/v1/routes/parse"]["post"]["responses"]
    assert _ref(responses["200"]).endswith("/RouteSummary")


@pytest.mark.parametrize("status", ["400", "413", "422", "500"])
def test_error_statuses_are_error_response(spec: Schema, status: str) -> None:
    responses = spec["paths"]["/v1/routes/parse"]["post"]["responses"]
    assert _ref(responses[status]).endswith("/ErrorResponse")


def test_no_http_validation_error_schema_exists(spec: Schema) -> None:
    schemas = spec["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas
    assert "HTTPValidationError" not in str(spec["paths"])


def test_request_body_is_multipart_with_a_binary_file_field(spec: Schema) -> None:
    body = spec["paths"]["/v1/routes/parse"]["post"]["requestBody"]
    ref = body["content"]["multipart/form-data"]["schema"]["$ref"]
    schema = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert schema["required"] == ["file"]
    assert schema["properties"]["file"]["contentMediaType"] == (
        "application/octet-stream"
    )


def test_points_are_capped_at_500_in_the_schema(spec: Schema) -> None:
    points = spec["components"]["schemas"]["RouteSummary"]["properties"]["points"]
    assert points["maxItems"] == 500
    assert points["minItems"] == 2


def test_every_route_summary_field_is_required(spec: Schema) -> None:
    schema = spec["components"]["schemas"]["RouteSummary"]
    assert set(schema["required"]) == set(schema["properties"])
    assert len(schema["properties"]) == 15


@pytest.mark.parametrize(
    "field", ["gain_m", "loss_m", "min_elev_m", "max_elev_m", "high_point"]
)
def test_nullable_fields_have_a_null_branch(spec: Schema, field: str) -> None:
    prop = spec["components"]["schemas"]["RouteSummary"]["properties"][field]
    assert {"type": "null"} in prop["anyOf"]


def test_error_code_enum_lists_every_documented_code(spec: Schema) -> None:
    code = spec["components"]["schemas"]["ErrorResponse"]["properties"]["code"]
    assert set(code["enum"]) == {
        "bad_request",
        "not_found",
        "method_not_allowed",
        "file_too_large",
        "invalid_gpx",
        "too_many_points",
        "too_few_points",
        "validation_error",
        "http_error",
        "internal_error",
    }


def test_elevation_source_and_source_format_enums(spec: Schema) -> None:
    props = spec["components"]["schemas"]["RouteSummary"]["properties"]
    assert set(props["elevation_source"]["enum"]) == {"file", "lookup", "none"}
    assert set(props["source_format"]["enum"]) == {"trk", "rte"}
