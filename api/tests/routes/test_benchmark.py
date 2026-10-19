"""Benchmark of the full pure pipeline on the largest fixture (ADR 0004 section 5).

Under ``api-test`` ``--benchmark-disable`` makes this a plain run-once correctness
test; only the ``benchmark`` CI job times it (``--benchmark-enable --benchmark-only``).
"""

from collections.abc import Callable
from typing import Protocol

from app.models.route import RouteSummary
from app.routes.summary import summarise_gpx
from tests.fixtures.loader import GPX_DIR, load_expected

LARGEST = "derived-ben-shemen-over-10k-points.gpx"


class Pedantic(Protocol):
    """The slice of pytest-benchmark's fixture used here (its pedantic is untyped)."""

    def pedantic(
        self,
        target: Callable[[bytes, str], RouteSummary],
        args: tuple[bytes, str],
        rounds: int,
        warmup_rounds: int,
        iterations: int,
    ) -> RouteSummary: ...


def test_largest_fixture_is_the_over_10k_one() -> None:
    sizes = {p.name: p.stat().st_size for p in GPX_DIR.glob("*.gpx")}
    assert max(sizes, key=lambda n: sizes[n]) == LARGEST


def test_parse_largest_fixture(benchmark: Pedantic) -> None:
    data = (GPX_DIR / LARGEST).read_bytes()  # read outside the timed call
    reference = load_expected()[LARGEST].reference_distance_m
    assert reference is not None
    result = benchmark.pedantic(
        summarise_gpx,
        args=(data, LARGEST),
        rounds=10,
        warmup_rounds=1,
        iterations=1,
    )
    # A "fast because broken" parser must fail here.
    assert abs(result.distance_m - reference) / reference <= 0.02
    assert len(result.points) == 500
    assert result.point_count_original == 10417
