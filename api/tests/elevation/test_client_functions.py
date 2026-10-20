"""The pure helpers of the elevation client (ADR 0005 sections 4 and 5)."""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.clients.elevation import (
    COORD_DECIMALS,
    ELEVATION_PATH,
    MAX_RESPONSE_BYTES,
    batch_query,
    format_coord,
    parse_elevations,
    split_batches,
)
from app.routes.params import (
    ELEVATION_BATCH_SIZE,
    ELEVATION_MAX_CALLS,
    ELEVATION_MAX_RETRIES,
    LOOKUP_MAX_POINTS,
    ParseParams,
)

Coords = list[tuple[float, float]]


def coords(n: int) -> Coords:
    return [(31.0 + i * 0.00123, 34.0 - i * 0.00071) for i in range(n)]


# --- the budget arithmetic (the checkpoint's "<= 5 calls" is a tested invariant) ---


def test_the_call_budget_constants_are_the_adr_values() -> None:
    assert ELEVATION_BATCH_SIZE == 100
    assert ELEVATION_MAX_RETRIES == 1
    assert ELEVATION_MAX_CALLS == 5
    assert LOOKUP_MAX_POINTS == 400
    assert COORD_DECIMALS == 5
    assert MAX_RESPONSE_BYTES == 64 * 1024
    assert ELEVATION_PATH == "/v1/elevation"


def test_batches_plus_one_retry_never_exceed_the_call_budget() -> None:
    batches = math.ceil(LOOKUP_MAX_POINTS / ELEVATION_BATCH_SIZE)
    assert batches + ELEVATION_MAX_RETRIES <= ELEVATION_MAX_CALLS


# --- format_coord ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (31.96259, "31.96259"),
        (34.9542, "34.95420"),
        (1.0, "1.00000"),
        (-0.5, "-0.50000"),
        (180.0, "180.00000"),
        (-90.0, "-90.00000"),
        (31.123456789, "31.12346"),
        (0.0, "0.00000"),
    ],
)
def test_format_coord_is_five_decimals(value: float, text: str) -> None:
    assert format_coord(value) == text


@settings(max_examples=200, derandomize=True, deadline=None)
@given(st.floats(-180, 180, allow_nan=False))
def test_format_coord_equals_the_fstring_for_any_coordinate(value: float) -> None:
    assert format_coord(value) == f"{value:.5f}"


# --- split_batches -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "sizes"),
    [
        (1, [1]),
        (99, [99]),
        (100, [100]),
        (101, [100, 1]),
        (250, [100, 100, 50]),
        (400, [100, 100, 100, 100]),
    ],
)
def test_split_batches_cuts_at_100(n: int, sizes: list[int]) -> None:
    batches = split_batches(coords(n))
    assert [len(b) for b in batches] == sizes


def test_split_batches_keeps_the_order_and_loses_nothing() -> None:
    original = coords(250)
    batches = split_batches(original)
    assert [c for batch in batches for c in batch] == original


def test_split_batches_honours_a_smaller_size() -> None:
    assert [len(b) for b in split_batches(coords(10), 3)] == [3, 3, 3, 1]


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.integers(1, 400), st.integers(1, 100))
def test_split_batches_properties(n: int, size: int) -> None:
    original = coords(n)
    batches = split_batches(original, size)
    assert len(batches) == math.ceil(n / size)
    assert all(1 <= len(b) <= size for b in batches)
    assert [c for batch in batches for c in batch] == original


# --- batch_query -------------------------------------------------------------------


def test_batch_query_comma_joins_five_decimal_values_with_no_spaces() -> None:
    query = batch_query([(31.96259, 34.9542), (31.9626, 34.95456), (-1.5, 180.0)])
    assert query == {
        "latitude": "31.96259,31.96260,-1.50000",
        "longitude": "34.95420,34.95456,180.00000",
    }


def test_batch_query_of_one_point_has_no_comma() -> None:
    assert batch_query([(1.0, 2.0)]) == {"latitude": "1.00000", "longitude": "2.00000"}


def test_batch_query_for_a_full_batch_stays_small() -> None:
    query = batch_query(coords(100))
    assert query["latitude"].count(",") == 99 and query["longitude"].count(",") == 99
    assert len(query["latitude"]) + len(query["longitude"]) < 2_000  # about 2 KB URL


# --- parse_elevations --------------------------------------------------------------


def test_parse_elevations_accepts_ints_and_floats_and_returns_floats() -> None:
    parsed = parse_elevations(b'{"elevation": [38, 12.5, -3.25, 0]}', 4)
    assert parsed == (38.0, 12.5, -3.25, 0.0)
    assert parsed is not None and all(type(v) is float for v in parsed)


def test_parse_elevations_ignores_extra_keys() -> None:
    assert parse_elevations(b'{"elevation": [1], "extra": {"a": 1}}', 1) == (1.0,)


@pytest.mark.parametrize("value", ["-1000", "10000", "-1000.0", "9999.99"])
def test_the_plausible_range_is_inclusive(value: str) -> None:
    assert parse_elevations(f'{{"elevation": [{value}]}}'.encode(), 1) == (
        float(value),
    )


BAD_BODIES = {
    "empty body": b"",
    "not json": b"<html>502 Bad Gateway</html>",
    "truncated json": b'{"elevation": [1, 2',
    "empty object": b"{}",
    "null": b"null",
    "top-level list": b"[1, 2, 3]",
    "elevation null": b'{"elevation": null}',
    "elevation string": b'{"elevation": "12"}',
    "elevation number": b'{"elevation": 12}',
    "elevation object": b'{"elevation": {"0": 12}}',
    "error object": b'{"error": true, "reason": "Latitude must be in range"}',
    "too few": b'{"elevation": [1, 2]}',
    "too many": b'{"elevation": [1, 2, 3, 4]}',
    "empty list": b'{"elevation": []}',
    "string element": b'{"elevation": [1, "12", 3]}',
    "bool element": b'{"elevation": [1, true, 3]}',
    "false element": b'{"elevation": [1, false, 3]}',
    "null element": b'{"elevation": [1, null, 3]}',
    "nested list element": b'{"elevation": [1, [2], 3]}',
    "NaN token": b'{"elevation": [1, NaN, 3]}',
    "Infinity token": b'{"elevation": [1, Infinity, 3]}',
    "-Infinity token": b'{"elevation": [1, -Infinity, 3]}',
    "overflowing exponent": b'{"elevation": [1, 1e999, 3]}',
    "negative overflowing exponent": b'{"elevation": [1, -1e999, 3]}',
    "above the plausible range": b'{"elevation": [1, 20000, 3]}',
    "just above the range": b'{"elevation": [1, 10000.001, 3]}',
    "below the plausible range": b'{"elevation": [1, -5000, 3]}',
    "just below the range": b'{"elevation": [1, -1000.001, 3]}',
    "invalid utf-8": b'{"elevation": [1, 2, 3], "x": "\xff\xfe"}',
}


@pytest.mark.parametrize("body", BAD_BODIES.values(), ids=BAD_BODIES.keys())
def test_parse_elevations_rejects_every_bad_body(body: bytes) -> None:
    assert parse_elevations(body, 3) is None


# --- ParseParams: the lookup knobs -------------------------------------------------


def test_lookup_defaults_are_the_adr_values() -> None:
    params = ParseParams()
    assert params.lookup_max_points == 400
    assert params.lookup_smoothing_window_m == 20.0
    assert params.lookup_gain_threshold_m == 9.5


@pytest.mark.parametrize("value", [3, 4, 100, 399, 400])
def test_lookup_max_points_inside_3_to_400_is_accepted(value: int) -> None:
    assert ParseParams(lookup_max_points=value).lookup_max_points == value


@pytest.mark.parametrize("value", [-1, 0, 1, 2, 401, 500, 10_000])
def test_lookup_max_points_outside_3_to_400_is_rejected(value: int) -> None:
    with pytest.raises(ValueError, match="lookup_max_points"):
        ParseParams(lookup_max_points=value)


@pytest.mark.parametrize(
    "name", ["lookup_smoothing_window_m", "lookup_gain_threshold_m"]
)
@pytest.mark.parametrize("value", [-0.1, -1.0, math.nan, math.inf, -math.inf])
def test_lookup_smoothing_values_must_be_non_negative_and_finite(
    name: str, value: float
) -> None:
    with pytest.raises(ValueError, match=name):
        ParseParams(**{name: value})  # type: ignore[arg-type]  # name picked by the test


@pytest.mark.parametrize(
    "name", ["lookup_smoothing_window_m", "lookup_gain_threshold_m"]
)
def test_lookup_smoothing_values_may_be_zero(name: str) -> None:
    assert getattr(ParseParams(**{name: 0.0}), name) == 0.0  # type: ignore[arg-type]  # name picked by the test
