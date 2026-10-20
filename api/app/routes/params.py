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
# An <ele> outside this range (inclusive) is treated as missing (ADR 0004 3.1 step 8).
MIN_PLAUSIBLE_ELEV_M: Final = -1000.0
MAX_PLAUSIBLE_ELEV_M: Final = 10000.0
# ADR 0004 3.12: the 100,001st point start tag the pass reads -> too_many_points
MAX_RAW_POINTS: Final = 100_000
PRETHIN_MAX_POINTS: Final = 2_000  # ADR 0004 3.5
RDP_TIE_TOLERANCE_M: Final = 1e-6  # ADR 0004 3.5 split rule
# ADR 0004 3.10: one parse at a time (memory budget and worst-case size are there)
MAX_CONCURRENT_PARSES: Final = 1
# ADR 0004 3.11: an element at depth 65 (the root is depth 1) -> invalid_gpx
MAX_XML_DEPTH: Final = 64
# ADR 0004 3.1 step 3 (round 3): expat allocation tracker; its defaults bound nothing
EXPAT_ALLOC_ACTIVATION_BYTES: Final = 32 * 1024 * 1024
EXPAT_ALLOC_MAX_AMPLIFICATION: Final = 4.0
# ADR 0004 3.1 text capture: the most characters kept of one <name> or <ele>
MAX_CAPTURED_TEXT_CHARS: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class ParseParams:
    resample_step_m: float = 5.0
    max_resample_points: int = 100_000
    # Tuned on the ADR 0004 §3.4 grid (window 20..80 m x T 3..15 m): the point with the
    # best worst-case margin to +-10 % gain on every valid fixture with elevation.
    smoothing_window_m: float = 20.0
    gain_threshold_m: float = 9.5
    loop_threshold_m: float = 200.0
    max_points: int = MAX_SUMMARY_POINTS  # 3 <= max_points <= MAX_SUMMARY_POINTS
    # >= 2 * max_points, so pre-thinning always leaves RDP room to fill its budget
    prethin_max_points: int = PRETHIN_MAX_POINTS

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
        if self.prethin_max_points < 2 * self.max_points:
            raise ValueError("prethin_max_points must be at least 2 * max_points")


DEFAULT_PARAMS: Final = ParseParams()
