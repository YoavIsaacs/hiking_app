"""The only home for parameters and limits of the GPX pipeline (ADR 0004 §1)."""

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
        """Contract: ValueError on out-of-range values. Stub: accepts everything."""
        return


DEFAULT_PARAMS: Final = ParseParams()
