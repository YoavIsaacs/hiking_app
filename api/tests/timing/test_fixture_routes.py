"""Plausibility on the AllTrails fixtures via the real parse pipeline (ADR 0006 §8)."""

import sys

import pytest

from app.models.route import RouteSummary
from app.routes.summary import summarise_gpx
from app.timing.estimate import estimate
from tests.fixtures.loader import GPX_DIR
from tests.timing.routes import FLAT_SPEED_KMH, START

# stem -> (moving_min band, total_min band), ADR 0006 §8
BANDS = {
    "alltrails-tel-hadid-loop": ((74.0, 91.5), (86.3, 106.7)),
    "alltrails-modiin-hills-south-double-loop": ((98.2, 121.5), (114.6, 141.8)),
    "alltrails-ben-shemen-hertzl-singletrack": ((122.5, 151.5), (142.9, 176.8)),
}


def summary(stem: str) -> RouteSummary:
    path = GPX_DIR / f"{stem}.gpx"
    return summarise_gpx(path.read_bytes(), path.name)


@pytest.mark.parametrize("stem", BANDS)
def test_fixture_times_fall_in_the_plausibility_band(stem: str) -> None:
    moving_band, total_band = BANDS[stem]
    t = estimate(summary(stem), START, 1.0, 10.0)
    sys.stderr.write(
        f"{stem}: moving {t.moving_min:.1f} min, total {t.total_min:.1f} min\n"
    )
    assert moving_band[0] <= t.moving_min <= moving_band[1]
    assert total_band[0] <= t.total_min <= total_band[1]


@pytest.mark.parametrize("stem", BANDS)
def test_fixture_has_an_eta_for_every_point_and_ends_at_finish(stem: str) -> None:
    route = summary(stem)
    t = estimate(route, START, 1.0, 10.0)
    assert len(t.eta_by_point) == len(route.points)
    assert t.eta_by_point[-1] == t.finish


def test_route_without_elevation_is_exactly_flat_time() -> None:
    route = summary("derived-tel-hadid-no-ele")
    assert route.elevation_source == "none"
    t = estimate(route, START, 1.0, 0.0)
    assert t.moving_min == pytest.approx(
        0.06 * route.distance_m / FLAT_SPEED_KMH, rel=1e-9
    )
