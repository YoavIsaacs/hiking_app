"""Tobler's hiking function (ADR 0006 §1)."""

import math


def speed_kmh(slope: float) -> float:
    """6 * exp(-3.5 * |slope + 0.05|) km/h; ValueError if not finite; no clamp."""
    if not math.isfinite(slope):
        raise ValueError("slope must be finite")
    return 6.0 * math.exp(-3.5 * abs(slope + 0.05))
