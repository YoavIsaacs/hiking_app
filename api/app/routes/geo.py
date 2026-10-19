"""Distance and loop detection (haversine, metres, 2-D)."""

from collections.abc import Sequence

from app.routes.params import DEFAULT_PARAMS
from app.routes.track import RawPoint


def geodesic_distance(a: RawPoint, b: RawPoint) -> float:
    raise NotImplementedError


def cumulative_distance(points: Sequence[RawPoint]) -> tuple[float, ...]:
    """[0.0, ...] with len == len(points)."""
    raise NotImplementedError


def is_loop(
    start: RawPoint,
    end: RawPoint,
    *,
    threshold_m: float = DEFAULT_PARAMS.loop_threshold_m,
) -> bool:
    raise NotImplementedError
