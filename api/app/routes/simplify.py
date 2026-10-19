"""Ranked Ramer-Douglas-Peucker simplification (ADR 0004 §3.5)."""

from collections.abc import Collection, Sequence

from app.routes.params import DEFAULT_PARAMS
from app.routes.track import RawPoint


def rdp_significance(points: Sequence[RawPoint]) -> tuple[float, ...]:
    """inf at both ends; iterative, no recursion."""
    raise NotImplementedError


def simplify(
    points: Sequence[RawPoint],
    *,
    keep: Collection[int] = (),
    max_points: int = DEFAULT_PARAMS.max_points,
) -> tuple[int, ...]:
    """Sorted indices, len == min(n, max_points)."""
    raise NotImplementedError
