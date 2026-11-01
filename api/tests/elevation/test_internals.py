"""Unit tests for helpers and wiring the ADR 0005 acceptance tests do not reach."""

import json
import logging
import math

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from app.clients.elevation import ElevationClient, parse_elevations
from app.config import Settings
from app.logging_config import configure_logging
from app.main import create_app
from app.routes.params import DEFAULT_PARAMS, LOOKUP_MAX_POINTS, ParseParams
from app.routes.summary import lookup_point_count


def test_an_integer_too_large_for_a_float_is_a_bad_body() -> None:
    body = json.dumps({"elevation": [10**400]}).encode()
    assert parse_elevations(body, 1) is None


# --- lookup_point_count (ADR 0005 5 and Amendment 1) --------------------------------


def test_spacing_off_gives_the_cap() -> None:
    params = ParseParams(lookup_spacing_m=0.0)
    assert lookup_point_count(0.0, params) == LOOKUP_MAX_POINTS
    assert lookup_point_count(1e9, params) == LOOKUP_MAX_POINTS


@pytest.mark.parametrize(
    ("distance_m", "expected"),
    [
        (0.0, 3),  # tiny distances give 3
        (50.0, 3),
        (180.0, 3),  # exactly two spacings: 2 + 1
        (180.1, 4),
        (900.0, 11),  # exact multiple: 10 + 1
        (6400.0, 73),  # Tel Hadid: ceil(71.1) + 1
        (36_000.0, 400),  # reaches the cap
        (1e9, 400),
    ],
)
def test_spacing_90_counts_one_point_per_spacing_plus_one(
    distance_m: float, expected: int
) -> None:
    assert (
        lookup_point_count(distance_m, ParseParams(lookup_spacing_m=90.0)) == expected
    )


def test_max_points_below_the_cap_wins() -> None:
    params = ParseParams(max_points=30, lookup_spacing_m=0.0)
    assert lookup_point_count(1e6, params) == 30
    assert lookup_point_count(1e6, ParseParams(max_points=30)) == 30


@settings(max_examples=200, derandomize=True, deadline=None)
@given(
    st.floats(0, 1e8, allow_nan=False),
    st.floats(0, 500, allow_nan=False),
    st.integers(3, 500),
    st.integers(3, 400),
)
def test_the_count_always_lies_in_3_to_the_cap(
    distance_m: float, spacing: float, max_points: int, lookup_max: int
) -> None:
    params = ParseParams(
        max_points=max_points, lookup_max_points=lookup_max, lookup_spacing_m=spacing
    )
    cap = min(max_points, lookup_max)
    assert 3 <= lookup_point_count(distance_m, params) <= cap


@pytest.mark.parametrize("value", [-0.1, math.nan, math.inf, -math.inf])
def test_lookup_spacing_must_be_non_negative_and_finite(value: float) -> None:
    with pytest.raises(ValueError, match="lookup_spacing_m"):
        ParseParams(lookup_spacing_m=value)


def test_lookup_spacing_may_be_zero_and_defaults_to_the_picked_value() -> None:
    assert ParseParams(lookup_spacing_m=0.0).lookup_spacing_m == 0.0
    assert DEFAULT_PARAMS.lookup_spacing_m > 0


# --- lifespan wiring -----------------------------------------------------------------


def test_the_lifespan_owns_an_elevation_client_for_its_lifetime(
    settings: Settings,
) -> None:
    app = create_app(settings)
    assert app.state.elevation_lookup is None
    with TestClient(app):
        assert isinstance(app.state.elevation_lookup, ElevationClient)
    assert app.state.elevation_lookup is None


def test_the_lifespan_resets_the_client_even_when_the_app_fails(
    settings: Settings,
) -> None:
    app = create_app(settings)
    with pytest.raises(RuntimeError, match="boom"), TestClient(app):
        raise RuntimeError("boom")
    assert app.state.elevation_lookup is None


def test_httpx_request_lines_are_not_logged_so_coordinates_stay_out_of_logs() -> None:
    configure_logging("INFO")
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)
