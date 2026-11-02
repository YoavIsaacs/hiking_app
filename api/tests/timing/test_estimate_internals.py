"""Unit tests for estimate.py internals (backend-owned)."""

import pytest

from app.models.route import RouteSummary
from app.timing.estimate import estimate, segment_slopes
from tests.timing.routes import START, evenly, make_route

# Routes whose first dist_m > 0: the 100 m window overhangs the start on the first
# segments, which a window clamped to 0 (not to dists[0]) gets wrong.
OFFSETS = [20.0, 1000.0]


def _route(offset_m: float) -> RouteSummary:
    """500 m at a uniform 10 % grade, 10 m steps, first dist_m = offset_m."""
    dists = [d + offset_m for d in evenly(500.0, 10.0)]
    return make_route(dists, [0.1 * d for d in dists])


@pytest.mark.parametrize("offset", OFFSETS)
def test_nonzero_first_dist_has_uniform_slope(offset: float) -> None:
    assert segment_slopes(_route(offset).points) == pytest.approx([0.1] * 50)


@pytest.mark.parametrize("offset", OFFSETS)
def test_nonzero_first_dist_same_moving_time_as_zero_start(offset: float) -> None:
    shifted = estimate(_route(offset), START, 1.0, 0.0)
    zero = estimate(_route(0.0), START, 1.0, 0.0)
    assert shifted.moving_min == pytest.approx(zero.moving_min)
