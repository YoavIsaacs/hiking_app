"""Timing constants (ADR 0006). The only home for them; imports nothing from app."""

from typing import Final

SLOPE_WINDOW_M: Final = 100.0  # minimum horizontal chord (ADR 0006 §2)
MAX_ABS_SLOPE: Final = 0.5  # slope clamp, rise/run (ADR 0006 §2)
DEFAULT_PACE_FACTOR: Final = 1.0
DEFAULT_REST_MIN_PER_HOUR: Final = 10.0
MIN_PACE_FACTOR: Final = 0.25
MAX_PACE_FACTOR: Final = 4.0
MAX_REST_MIN_PER_HOUR: Final = 60.0
