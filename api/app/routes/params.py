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
# ADR 0004 3.1 step 4 / 3.11 "Why a URI cap": a declared namespace URI that is not
# ASCII or is longer than this many characters gets invalid_gpx TOO_COMPLEX_MESSAGE
MAX_NAMESPACE_URI_CHARS: Final = 256
# ADR 0005 5: Open-Meteo allows up to 100 coordinates per request
ELEVATION_BATCH_SIZE: Final = 100
ELEVATION_MAX_RETRIES: Final = 1  # per lookup (per route), shared by its batches
ELEVATION_MAX_CALLS: Final = 5  # roadmap 1.3 checkpoint
LOOKUP_MAX_POINTS: Final = (
    ELEVATION_MAX_CALLS - ELEVATION_MAX_RETRIES
) * ELEVATION_BATCH_SIZE  # 400


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
    # ADR 0005 3/5: 3..LOOKUP_MAX_POINTS; effective = min(this, max_points)
    lookup_max_points: int = LOOKUP_MAX_POINTS
    # ADR 0005 Amendment 1 / 3: finite, >= 0; 0 = off. These three come from the
    # section 3 grid on the recorded Open-Meteo responses (tools/elevation_grid.py,
    # output in tools/elevation_grid_output.txt): the largest spacing among the points
    # within 3 pp of the best worst-case margin (+13.1 pp; Tel Hadid 104.99 m vs 103 m).
    lookup_spacing_m: float = 90.0
    lookup_smoothing_window_m: float = 135.0
    lookup_gain_threshold_m: float = 3.0

    def __post_init__(self) -> None:
        """Raise ValueError on nonsense values (a programming error)."""
        if not (math.isfinite(self.resample_step_m) and self.resample_step_m > 0):
            raise ValueError("resample_step_m must be a positive finite number")
        if self.max_resample_points < 1:
            raise ValueError("max_resample_points must be at least 1")
        for name in (
            "smoothing_window_m",
            "gain_threshold_m",
            "loop_threshold_m",
            "lookup_spacing_m",
            "lookup_smoothing_window_m",
            "lookup_gain_threshold_m",
        ):
            value: float = getattr(self, name)
            if not (math.isfinite(value) and value >= 0):
                raise ValueError(f"{name} must be a non-negative finite number")
        if not 3 <= self.max_points <= MAX_SUMMARY_POINTS:
            raise ValueError(f"max_points must be within 3..{MAX_SUMMARY_POINTS}")
        if not 3 <= self.lookup_max_points <= LOOKUP_MAX_POINTS:
            raise ValueError(f"lookup_max_points must be within 3..{LOOKUP_MAX_POINTS}")
        if self.prethin_max_points < 2 * self.max_points:
            raise ValueError("prethin_max_points must be at least 2 * max_points")


DEFAULT_PARAMS: Final = ParseParams()
