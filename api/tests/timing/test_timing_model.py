"""The Timing contract (ADR 0006 §6)."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.timing import Timing

T0 = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)


def valid(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "start": T0,
        "finish": T1,
        "moving_min": 50.0,
        "total_min": 60.0,
        "eta_by_point": [T0, T1],
    }
    return base | over


def test_valid_timing_builds_and_is_frozen() -> None:
    t = Timing.model_validate(valid())
    with pytest.raises(ValidationError):
        t.moving_min = 1.0  # type: ignore[misc]  # frozen on purpose


@pytest.mark.parametrize(
    "over",
    [
        {"start": datetime(2026, 6, 1, 6, 0)},
        {"finish": datetime(2026, 6, 1, 7, 0)},
        {"moving_min": -0.1},
        {"total_min": -0.1},
        {"moving_min": float("nan")},
        {"total_min": float("inf")},
        {"eta_by_point": [T0]},
        {"eta_by_point": [T0] * 501},
        {"eta_by_point": [T0, datetime(2026, 6, 1, 7, 0)]},
        {"extra": 1},
    ],
)
def test_invalid_timing_is_rejected(over: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Timing.model_validate(valid(**over))


def test_500_etas_are_allowed() -> None:
    assert (
        len(Timing.model_validate(valid(eta_by_point=[T0] * 500)).eta_by_point) == 500
    )
