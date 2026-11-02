"""Tobler's hiking function (ADR 0006 §1)."""


def speed_kmh(slope: float) -> float:
    """6 * exp(-3.5 * |slope + 0.05|) km/h; ValueError if not finite; no clamp."""
    raise NotImplementedError
