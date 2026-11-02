"""Duration estimator (ADR 0006 §2-§6). Pure: no I/O, clock, randomness or settings."""

from collections.abc import Sequence
from datetime import datetime

from app.models.route import RouteSummary, TrackPoint
from app.models.timing import Timing


def segment_slopes(points: Sequence[TrackPoint]) -> list[float]:
    """len(points) - 1 windowed, clamped slopes (ADR 0006 §2/§3).

    Raises ValueError if dist_m decreases.
    """
    raise NotImplementedError


def estimate(
    route: RouteSummary,
    start_time: datetime,
    pace_factor: float,
    rest_min_per_hour: float,
) -> Timing:
    """Time the route (ADR 0006 §4-§6).

    Raises ValueError on a naive start_time, out-of-range pace or rest, or
    decreasing dist_m.
    """
    raise NotImplementedError
