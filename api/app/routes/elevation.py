"""Elevation smoothing and gain/loss (ADR 0004 §3.4)."""

import math
from collections.abc import Sequence
from itertools import accumulate

from app.routes.params import DEFAULT_PARAMS


def _resample(
    dist_m: Sequence[float], elev_m: Sequence[float], step_m: float, max_samples: int
) -> tuple[list[float], float]:
    """Sample the piecewise-linear profile on a uniform grid; return (series, spacing).

    Both ends are exact. At repeated distances the later point wins. A zero-length
    profile returns its two endpoint elevations.
    """
    start, end = dist_m[0], dist_m[-1]
    length = end - start
    if length <= 0:
        return [elev_m[0], elev_m[-1]], 0.0
    n = min(max(1, math.ceil(length / step_m)), max_samples)
    last = len(dist_m) - 1
    series: list[float] = []
    j = 0
    for k in range(n + 1):
        if k == n:
            series.append(elev_m[last])
            break
        t = start + length * k / n
        while j < last and dist_m[j + 1] <= t:
            j += 1
        if j == last or dist_m[j] == t:
            series.append(elev_m[j])
        else:
            frac = (t - dist_m[j]) / (dist_m[j + 1] - dist_m[j])
            series.append(elev_m[j] + (elev_m[j + 1] - elev_m[j]) * frac)
    return series, length / n


def smooth_elevation(
    dist_m: Sequence[float],
    elev_m: Sequence[float],
    *,
    window_m: float = DEFAULT_PARAMS.smoothing_window_m,
    step_m: float = DEFAULT_PARAMS.resample_step_m,
    max_samples: int = DEFAULT_PARAMS.max_resample_points,
) -> tuple[float, ...]:
    """Resampled uniform grid (both ends included), centred moving average.

    The window is in metres along the track, so the result does not depend on point
    density. It shrinks symmetrically at the ends, which keeps the end samples raw and
    passes any linear profile through unchanged.
    """
    series, spacing = _resample(dist_m, elev_m, step_m, max_samples)
    if spacing <= 0 or window_m <= 0:
        return tuple(series)
    half = math.floor(window_m / (2 * spacing))
    if half == 0:
        return tuple(series)
    last = len(series) - 1
    prefix = [0.0, *accumulate(series)]
    smoothed: list[float] = []
    for k, raw in enumerate(series):
        h = min(half, k, last - k)
        smoothed.append(
            raw if h == 0 else (prefix[k + h + 1] - prefix[k - h]) / (2 * h + 1)
        )
    return tuple(smoothed)


def gain_loss(
    elev_m: Sequence[float],
    *,
    threshold_m: float = DEFAULT_PARAMS.gain_threshold_m,
) -> tuple[float, float]:
    """Return (gain, loss) using Schmitt-trigger hysteresis with threshold T.

    Legs between confirmed extremes are collected and summed per sign with fsum, so the
    result is independent of summation order. gain - loss telescopes to last - first and
    reversing the series swaps the two results exactly. Thresholds are tested on the
    float difference itself (never on `x + T`), because a - b is exactly -(b - a).
    """
    if len(elev_m) < 2:
        return 0.0, 0.0
    if threshold_m <= 0:
        steps = [b - a for a, b in zip(elev_m, elev_m[1:], strict=False)]
        return (
            math.fsum(s for s in steps if s > 0),
            math.fsum(-s for s in steps if s < 0),
        )

    gains: list[float] = []
    losses: list[float] = []

    def leg(delta: float) -> None:
        (gains if delta > 0 else losses).append(abs(delta))

    first = elev_m[0]
    low = high = first
    direction = 0  # 0 undetermined, 1 up (following a max), -1 down (following a min)
    extreme = first  # last confirmed extreme
    candidate = first
    for y in elev_m[1:]:
        if direction == 0:
            if y - low >= threshold_m:
                leg(low - first)
                extreme, candidate, direction = low, y, 1
            elif high - y >= threshold_m:
                leg(high - first)
                extreme, candidate, direction = high, y, -1
            else:
                low, high = min(low, y), max(high, y)
        elif direction == 1:
            if y > candidate:
                candidate = y
            elif candidate - y >= threshold_m:
                leg(candidate - extreme)
                extreme, candidate, direction = candidate, y, -1
        else:
            if y < candidate:
                candidate = y
            elif y - candidate >= threshold_m:
                leg(candidate - extreme)
                extreme, candidate, direction = candidate, y, 1
    if direction == 0:
        leg(elev_m[-1] - first)
    else:
        leg(candidate - extreme)
        leg(elev_m[-1] - candidate)
    return math.fsum(gains), math.fsum(losses)


def high_point_index(elev_m: Sequence[float]) -> int:
    """First index of the maximum; ValueError if empty."""
    if not elev_m:
        raise ValueError("high_point_index of an empty sequence")
    best = 0
    for i, value in enumerate(elev_m):
        if value > elev_m[best]:
            best = i
    return best
