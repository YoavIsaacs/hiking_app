"""Regression: collinear tracks must not make rdp_significance quadratic."""

import math

from app.routes.simplify import rdp_significance, simplify
from app.routes.summary import summarise_gpx
from app.routes.track import RawPoint


def test_ties_split_near_the_midpoint() -> None:
    pts = [RawPoint(i * 1e-4, 0.0, None) for i in range(9)]  # exact ties (d == 0)
    sig = rdp_significance(pts)
    assert math.isinf(sig[0]) and math.isinf(sig[8])
    assert all(s == 0.0 for s in sig[1:8])


def test_100k_exactly_collinear_points_rank_quickly() -> None:
    # 100k points, all distances exactly 0: first-index ties need ~5e9 evaluations.
    pts = [RawPoint(i * 1e-6, 0.0, 100.0) for i in range(100_000)]
    sig = rdp_significance(pts)
    assert len(sig) == 100_000
    assert len(simplify(pts, max_points=500)) == 500


def test_100k_collinear_points_with_float_noise_rank_quickly() -> None:
    pts = [RawPoint(0.0, i * 1e-6, 100.0) for i in range(100_000)]
    sig = rdp_significance(pts)
    assert len(sig) == 100_000
    assert len(simplify(pts, max_points=500)) == 500


def test_near_10mib_straight_line_gpx_summarises() -> None:
    n = 170_000
    body = "".join(
        f'<trkpt lat="31.0" lon="{34.0 + i * 1e-6:.6f}"><ele>100</ele></trkpt>'
        for i in range(n)
    )
    gpx = (
        '<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{body}</trkseg></trk></gpx>"
    ).encode()
    assert len(gpx) > 9_000_000
    summary = summarise_gpx(gpx, "line.gpx")
    assert summary.distance_m > 0
