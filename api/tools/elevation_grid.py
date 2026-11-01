"""ADR 0005 section 3 grid: pick the lookup spacing, smoothing window and threshold.

Replays QA's recorded Open-Meteo responses (tests/fixtures/http/elevation/) against the
three AllTrails parents with ``<ele>`` stripped, over spacing x window x T, and applies
the deterministic pick rule. Run from api/: ``uv run python -m tools.elevation_grid``.
Pure computation on committed files: no network.
"""

import math
import sys
from dataclasses import dataclass, replace
from typing import Final

from app.routes.elevation import gain_loss, smooth_elevation
from app.routes.params import ELEVATION_BATCH_SIZE, ParseParams
from app.routes.parse import parse_gpx
from app.routes.summary import summarise_track
from app.routes.track import RawPoint, RawTrack
from tests.elevation_support import (
    BEN_SHEMEN,
    MODIIN,
    TEL_HADID,
    pair_of,
    recorded_table,
)
from tests.fixtures.loader import GPX_DIR

REFERENCE_M: Final = {TEL_HADID: 103.0, MODIIN: 198.0, BEN_SHEMEN: 200.0}
SPACINGS: Final = (0.0, 45.0, 90.0, 135.0)
WINDOWS: Final = (0.0, 20.0, 45.0, 90.0, 135.0, 180.0)
THRESHOLDS: Final = tuple(2.0 + 0.5 * k for k in range(21))
GATE: Final = 0.15
GIVE_UP_PP: Final = 0.03
SANITY: Final = (0.0, 20.0, 9.5, 181.18)  # spacing, window, T, Tel Hadid gain


@dataclass(frozen=True)
class Cell:
    spacing: float
    window: float
    threshold: float
    points: dict[str, int]
    gain: dict[str, float]

    def error(self, stem: str) -> float:
        return (self.gain[stem] - REFERENCE_M[stem]) / REFERENCE_M[stem]

    @property
    def margin(self) -> float:
        return GATE - max(abs(self.error(s)) for s in REFERENCE_M)

    @property
    def feasible(self) -> bool:
        return abs(self.error(TEL_HADID)) <= GATE


def _stripped(stem: str) -> RawTrack:
    track = parse_gpx((GPX_DIR / f"{stem}.gpx").read_bytes())
    return replace(
        track, points=tuple(RawPoint(p.lat, p.lon, None) for p in track.points)
    )


def run_grid() -> list[Cell]:
    tracks = {stem: _stripped(stem) for stem in REFERENCE_M}
    tables = {stem: recorded_table(stem) for stem in REFERENCE_M}
    base = ParseParams()
    cells: list[Cell] = []
    for spacing in SPACINGS:
        params = replace(base, lookup_spacing_m=spacing)
        stage1 = {s: summarise_track(t, "g.gpx", params) for s, t in tracks.items()}
        dists = {s: [p.dist_m for p in r.points] for s, r in stage1.items()}
        elevs = {
            s: [tables[s][pair_of(p.lat, p.lon)] for p in r.points]
            for s, r in stage1.items()
        }
        counts = {s: len(r.points) for s, r in stage1.items()}
        for window in WINDOWS:
            smoothed = {
                s: smooth_elevation(
                    dists[s],
                    elevs[s],
                    window_m=window,
                    step_m=base.resample_step_m,
                    max_samples=base.max_resample_points,
                )
                for s in stage1
            }
            for t in THRESHOLDS:
                gains = {s: gain_loss(smoothed[s], threshold_m=t)[0] for s in stage1}
                cells.append(Cell(spacing, window, t, counts, gains))
    return cells


def pick(cells: list[Cell]) -> tuple[Cell | None, float | None, int, int]:
    """(pick, M*, feasible count, acceptable count); pick None when none is feasible."""
    feasible = [c for c in cells if c.feasible]
    if not feasible:
        return None, None, 0, 0
    best = max(c.margin for c in feasible)
    floor = max(0.0, best - GIVE_UP_PP)
    acceptable = [c for c in feasible if c.margin >= floor]
    if not acceptable:
        return None, best, len(feasible), 0
    chosen = min(
        acceptable,
        key=lambda c: (
            c.spacing == 0,  # spacing off ranks last
            -c.spacing,
            -c.margin,
            c.window,
            c.threshold,
        ),
    )
    return chosen, best, len(feasible), len(acceptable)


def _row(c: Cell) -> str:
    calls = [math.ceil(c.points[s] / ELEVATION_BATCH_SIZE) for s in REFERENCE_M]
    cols = [f"{c.spacing:g}", f"{c.window:g}", f"{c.threshold:g}"]
    cols += [f"{c.points[s]} / {k}" for s, k in zip(REFERENCE_M, calls, strict=True)]
    for s in REFERENCE_M:
        cols += [f"{c.gain[s]:.2f}", f"{c.error(s) * 100:+.1f}%"]
    cols.append(f"{c.margin * 100:+.1f} pp")
    return "| " + " | ".join(cols) + " |"


HEADER: Final = (
    "| spacing | window | T | pts/calls Tel Hadid | pts/calls Modiin "
    "| pts/calls Ben Shemen | Tel Hadid gain | e | Modiin gain | e "
    "| Ben Shemen gain | e | m |\n"
    "|" + " --- |" * 13
)


def neighbours(cells: list[Cell], c: Cell) -> list[str]:
    index = {(x.spacing, x.window, x.threshold): x for x in cells}
    out: list[str] = []
    for axis, values in (
        ("spacing", SPACINGS),
        ("window", WINDOWS),
        ("T", THRESHOLDS),
    ):
        current = {"spacing": c.spacing, "window": c.window, "T": c.threshold}[axis]
        k = values.index(current)
        for step in (-1, 1):
            if 0 <= k + step < len(values):
                key = {"spacing": c.spacing, "window": c.window, "T": c.threshold}
                key[axis] = values[k + step]
                n = index[(key["spacing"], key["window"], key["T"])]
                out.append(f"{axis}={values[k + step]:g}: m {n.margin * 100:+.1f} pp")
            else:
                out.append(f"{axis} step {step:+d}: edge of the grid")
    return out


def report(cells: list[Cell]) -> str:
    lines: list[str] = []
    sanity = next(c for c in cells if (c.spacing, c.window, c.threshold) == SANITY[:3])
    ok = abs(sanity.gain[TEL_HADID] - SANITY[3]) <= 0.01
    lines.append(
        "Sanity row (spacing 0, 20 m, 9.5 m): Tel Hadid "
        f"{sanity.gain[TEL_HADID]:.2f} m, "
        f"QA says {SANITY[3]:.2f} m: {'reproduced' if ok else 'MISMATCH, stop'}"
    )
    chosen, best, n_feasible, n_acceptable = pick(cells)
    lines.append(
        f"Grid points: {len(cells)}; feasible: {n_feasible}; "
        f"acceptable: {n_acceptable}; M*: "
        + ("none" if best is None else f"{best * 100:+.1f} pp")
    )
    lines += ["", "Best T per (spacing, window):", "", HEADER]
    for spacing in SPACINGS:
        for window in WINDOWS:
            row = [c for c in cells if c.spacing == spacing and c.window == window]
            lines.append(_row(max(row, key=lambda c: (c.margin, -c.threshold))))
    lines += ["", "Pick:", ""]
    if chosen is None:
        lines.append("No feasible or acceptable point: escalate (ADR 0005 section 3).")
    else:
        lines += [HEADER, _row(chosen), "", "Neighbours (one grid step):"]
        lines += [f"- {n}" for n in neighbours(cells, chosen)]
    return "\n".join(lines)


def main() -> int:
    sys.stdout.write(report(run_grid()) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
