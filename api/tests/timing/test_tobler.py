"""Tobler's hiking function (ADR 0006 §1)."""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.timing.tobler import speed_kmh

TABLE = [
    (-0.05, 6.0),
    (0.0, 5.03674),
    (-0.10, 5.03674),
    (0.10, 3.54933),
    (0.20, 2.50117),
    (-0.30, 2.50117),
    (0.30, 1.76255),
    (0.50, 0.875254),
    (-0.50, 1.242044),
]


@pytest.mark.parametrize(("slope", "kmh"), TABLE)
def test_speed_matches_tobler_table(slope: float, kmh: float) -> None:
    assert speed_kmh(slope) == pytest.approx(kmh, rel=1e-5)


def test_steep_uphill_is_slower_than_flat() -> None:
    assert speed_kmh(0.2) < speed_kmh(0.0)


def test_gentle_downhill_is_faster_than_flat() -> None:
    assert speed_kmh(-0.05) > speed_kmh(0.0)


def test_steep_downhill_is_slower_than_flat() -> None:
    assert speed_kmh(-0.3) < speed_kmh(0.0)


def test_speed_is_not_clamped_beyond_the_estimator_clamp() -> None:
    assert speed_kmh(5.0) == pytest.approx(6.0 * math.exp(-3.5 * 5.05), rel=1e-9)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_slope_raises(bad: float) -> None:
    with pytest.raises(ValueError):
        speed_kmh(bad)


@given(st.floats(min_value=-1.0, max_value=1.0))
def test_speed_never_exceeds_6_kmh_and_is_positive(slope: float) -> None:
    assert 0.0 < speed_kmh(slope) <= 6.0


@given(
    st.floats(min_value=-1.0, max_value=1.0),
    st.floats(min_value=-1.0, max_value=1.0),
)
def test_speed_strictly_decreases_away_from_minus_5_percent(a: float, b: float) -> None:
    near, far = sorted((a, b), key=lambda s: abs(s + 0.05))
    if abs(far + 0.05) - abs(near + 0.05) < 1e-9:
        return  # indistinguishable distances: no strict claim
    assert speed_kmh(near) > speed_kmh(far)
