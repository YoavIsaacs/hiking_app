"""The only home for parameters and limits of the GPX pipeline (ADR 0004 §1)."""

import math
from dataclasses import dataclass
from typing import Final

MAX_UPLOAD_BYTES: Final = 10 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES: Final = 64 * 1024
MAX_SUMMARY_POINTS: Final = 500
EARTH_RADIUS_M: Final = 6_371_008.8
MAX_NAME_LENGTH: Final = 200
UNTITLED_ROUTE_NAME: Final = "Untitled route"


@dataclass(frozen=True, slots=True)
class ParseParams:
    resample_step_m: float = 5.0
    max_resample_points: int = 100_000
    smoothing_window_m: float = 30.0  # tuned per ADR 0004 §3.4; starting value
    gain_threshold_m: float = 10.0  # tuned per ADR 0004 §3.4; starting value
    loop_threshold_m: float = 200.0
    max_points: int = MAX_SUMMARY_POINTS  # 3 <= max_points <= MAX_SUMMARY_POINTS

    def __post_init__(self) -> None:
        """Raise ValueError on nonsense values (a programming error)."""
        if not (math.isfinite(self.resample_step_m) and self.resample_step_m > 0):
            raise ValueError("resample_step_m must be a positive finite number")
        if self.max_resample_points < 1:
            raise ValueError("max_resample_points must be at least 1")
        for name in ("smoothing_window_m", "gain_threshold_m", "loop_threshold_m"):
            value: float = getattr(self, name)
            if not (math.isfinite(value) and value >= 0):
                raise ValueError(f"{name} must be a non-negative finite number")
        if not 3 <= self.max_points <= MAX_SUMMARY_POINTS:
            raise ValueError(f"max_points must be within 3..{MAX_SUMMARY_POINTS}")


DEFAULT_PARAMS: Final = ParseParams()
