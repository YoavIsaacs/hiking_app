"""The ADR 0005 section 3 grid: the committed pick is what the grid says today."""

from pathlib import Path

import pytest

from app.routes.params import DEFAULT_PARAMS
from tools.elevation_grid import (
    GATE,
    REFERENCE_M,
    SPACINGS,
    THRESHOLDS,
    WINDOWS,
    Cell,
    neighbours,
    pick,
    report,
    run_grid,
)

OUTPUT = Path(__file__).parents[2] / "tools" / "elevation_grid_output.txt"


@pytest.fixture(scope="module")
def cells() -> list[Cell]:
    return run_grid()


def test_the_grid_has_the_504_points_of_the_adr(cells: list[Cell]) -> None:
    assert len(cells) == len(SPACINGS) * len(WINDOWS) * len(THRESHOLDS) == 504


def test_the_start_values_reproduce_qas_181_18_m(cells: list[Cell]) -> None:
    start = next(c for c in cells if (c.spacing, c.window, c.threshold) == (0, 20, 9.5))
    assert start.gain["alltrails-tel-hadid-loop"] == pytest.approx(181.18, abs=0.01)
    assert not start.feasible


def test_the_defaults_are_the_pick(cells: list[Cell]) -> None:
    chosen, best, n_feasible, n_acceptable = pick(cells)
    assert chosen is not None and best is not None
    assert (chosen.spacing, chosen.window, chosen.threshold) == (
        DEFAULT_PARAMS.lookup_spacing_m,
        DEFAULT_PARAMS.lookup_smoothing_window_m,
        DEFAULT_PARAMS.lookup_gain_threshold_m,
    )
    assert chosen.feasible and chosen.margin >= max(0.0, best - 0.03)
    assert all(abs(chosen.error(s)) <= GATE for s in REFERENCE_M)  # not one file's fit
    assert (n_feasible, n_acceptable) == (125, 7)


def test_the_committed_output_is_the_current_report(cells: list[Cell]) -> None:
    assert report(cells) + "\n" == OUTPUT.read_text(encoding="utf-8").replace(
        "\r\n", "\n"
    )


def test_neighbours_name_the_edges_of_the_grid(cells: list[Cell]) -> None:
    corner = next(c for c in cells if (c.spacing, c.window, c.threshold) == (0, 0, 2))
    assert any("edge of the grid" in n for n in neighbours(cells, corner))


def test_no_feasible_point_means_no_pick(cells: list[Cell]) -> None:
    infeasible = [c for c in cells if not c.feasible]
    assert pick(infeasible) == (None, None, 0, 0)
    assert "escalate" in report(infeasible)
