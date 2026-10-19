"""Elevation smoothing and gain/loss (ADR 0004 §3.4)."""

from collections.abc import Sequence

from app.routes.params import DEFAULT_PARAMS


def smooth_elevation(
    dist_m: Sequence[float],
    elev_m: Sequence[float],
    *,
    window_m: float = DEFAULT_PARAMS.smoothing_window_m,
    step_m: float = DEFAULT_PARAMS.resample_step_m,
    max_samples: int = DEFAULT_PARAMS.max_resample_points,
) -> tuple[float, ...]:
    """Resampled uniform grid (both ends included), centred moving average."""
    raise NotImplementedError


def gain_loss(
    elev_m: Sequence[float],
    *,
    threshold_m: float = DEFAULT_PARAMS.gain_threshold_m,
) -> tuple[float, float]:
    """Return (gain, loss)."""
    raise NotImplementedError


def high_point_index(elev_m: Sequence[float]) -> int:
    """First index of the maximum; ValueError if empty."""
    raise NotImplementedError
