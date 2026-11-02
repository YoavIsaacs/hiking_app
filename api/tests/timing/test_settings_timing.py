"""HIKE_PACE_FACTOR / HIKE_REST_MIN_PER_HOUR (ADR 0006 §4)."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.timing import params


def test_defaults_are_pace_1_and_rest_10() -> None:
    s = Settings(_env_file=None)
    assert (s.pace_factor, s.rest_min_per_hour) == (1.0, 10.0)


def test_env_overrides_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIKE_PACE_FACTOR", "1.3")
    monkeypatch.setenv("HIKE_REST_MIN_PER_HOUR", "0")
    s = Settings(_env_file=None)
    assert (s.pace_factor, s.rest_min_per_hour) == (1.3, 0.0)


@pytest.mark.parametrize("value", ["0.25", "4.0"])
def test_pace_bounds_are_inclusive(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("HIKE_PACE_FACTOR", value)
    assert Settings(_env_file=None).pace_factor == float(value)


@pytest.mark.parametrize(
    "value", ["0", "0.2", "4.1", "nan", "inf", "-inf", "-1", "fast", ""]
)
def test_pace_out_of_range_or_non_finite_is_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HIKE_PACE_FACTOR", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["0", "60"])
def test_rest_bounds_are_inclusive(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("HIKE_REST_MIN_PER_HOUR", value)
    assert Settings(_env_file=None).rest_min_per_hour == float(value)


@pytest.mark.parametrize("value", ["-1", "61", "nan", "inf", "-inf", "lots", ""])
def test_rest_out_of_range_or_non_finite_is_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HIKE_REST_MIN_PER_HOUR", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_bounds_come_from_timing_params() -> None:
    assert (
        Settings(_env_file=None, pace_factor=params.MIN_PACE_FACTOR).pace_factor == 0.25
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pace_factor=params.MAX_PACE_FACTOR + 0.001)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rest_min_per_hour=params.MAX_REST_MIN_PER_HOUR + 0.001)


def test_timing_params_values() -> None:
    assert params.SLOPE_WINDOW_M == 100.0
    assert params.MAX_ABS_SLOPE == 0.5
    assert (params.MIN_PACE_FACTOR, params.MAX_PACE_FACTOR) == (0.25, 4.0)
    assert params.MAX_REST_MIN_PER_HOUR == 60.0
    assert (params.DEFAULT_PACE_FACTOR, params.DEFAULT_REST_MIN_PER_HOUR) == (1.0, 10.0)
