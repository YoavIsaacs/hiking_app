r"""Step 1.4 checkpoint: one pace factor puts the estimate within +-20 % of real hikes.

MANAGER INSTRUCTIONS (PowerShell). The hike files are your data; they are NOT committed.

1. Put the 5 AllTrails .gpx files in docs\maps\hikes\ (any file names).
2. Create docs\maps\hikes\hikes.csv with this header and one row per hike:

       gpx_file,date,start_time_local,total_elapsed_min
       tel-hadid.gpx,2026-03-14,07:30,95

   date is YYYY-MM-DD, start_time_local is 24 h HH:MM (local clock time),
   total_elapsed_min is start to finish with every break included, in minutes.
   gpx_file is relative to the CSV.
3. From the api folder, run:

       cd D:\Programming\Projects\Hiking_App\hiking_app\api
       uv run python -m tools.timing_checkpoint

   Or name the CSV: uv run python -m tools.timing_checkpoint C:\path\hikes.csv
4. Copy the printed table into PROGRESS.md. Exit codes:
   0 = every hike within 20 %;
   1 = checkpoint FAIL (a hike is outside 20 %, or the fitted factor is outside
       the range the app allows);
   2 = bad input (missing file, bad row, under 5 hikes, a GPX without elevation,
       a CSV that is not UTF-8: save it as "CSV UTF-8");
   3 = internal error in this tool (message on stderr); NOT a checkpoint result.

What it does: parses each GPX through the real ``summarise_gpx`` pipeline, runs
``estimate`` at pace 1.0 and rest 10 min/h, fits ONE pace factor as the geometric
mean of real / estimated total time, and prints each hike's error at that factor.
Total time is linear in the pace factor, so the fit is exact. Local files only.
"""

import csv
import io
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Final, TextIO

from app.models.route import RouteSummary
from app.routes.errors import RouteParseError
from app.routes.summary import summarise_gpx
from app.timing.estimate import estimate
from app.timing.params import (
    DEFAULT_REST_MIN_PER_HOUR,
    MAX_PACE_FACTOR,
    MIN_PACE_FACTOR,
)

COLUMNS: Final = ("gpx_file", "date", "start_time_local", "total_elapsed_min")
MIN_HIKES: Final = 5
LIMIT_PCT: Final = 20.0
DEFAULT_MANIFEST: Final = (
    Path(__file__).parents[2] / "docs" / "maps" / "hikes" / "hikes.csv"
)
EXIT_OK, EXIT_FAIL, EXIT_BAD_INPUT, EXIT_INTERNAL_ERROR = 0, 1, 2, 3


class ManifestError(ValueError):
    """The manifest or one of the hikes it points at is unusable."""


@dataclass(frozen=True)
class Hike:
    gpx_file: str
    day: date
    start_local: time
    total_elapsed_min: float


def parse_manifest(text: str) -> list[Hike]:
    """Parse the CSV; raise ManifestError naming the row of the first problem."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    header = [h.strip() for h in reader.fieldnames or []]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise ManifestError(
            f"manifest is missing columns {missing}; need {list(COLUMNS)}"
        )
    hikes: list[Hike] = []
    for number, raw in enumerate(reader, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        hikes.append(_hike(number, row))
    if not hikes:
        raise ManifestError("manifest has no hikes")
    return hikes


def _hike(number: int, row: dict[str, str]) -> Hike:
    where = f"row {number}"
    if not row["gpx_file"]:
        raise ManifestError(f"{where}: gpx_file is empty")
    try:
        day = date.fromisoformat(row["date"])
    except ValueError:
        raise ManifestError(
            f"{where}: date {row['date']!r} is not YYYY-MM-DD"
        ) from None
    try:
        start = datetime.strptime(row["start_time_local"], "%H:%M").time()
    except ValueError:
        raise ManifestError(
            f"{where}: start_time_local {row['start_time_local']!r} is not HH:MM"
        ) from None
    try:
        minutes = float(row["total_elapsed_min"])
    except ValueError:
        raise ManifestError(
            f"{where}: total_elapsed_min {row['total_elapsed_min']!r} is not a number"
        ) from None
    if not math.isfinite(minutes) or minutes <= 0:
        raise ManifestError(f"{where}: total_elapsed_min must be a positive number")
    return Hike(row["gpx_file"], day, start, minutes)


def fit_pace_factor(real_min: Sequence[float], estimated_min: Sequence[float]) -> float:
    """Geometric mean of real / estimated (both at pace 1.0)."""
    if not real_min or len(real_min) != len(estimated_min):
        raise ValueError("need the same non-zero number of real and estimated times")
    if any(not math.isfinite(v) or v <= 0 for v in (*real_min, *estimated_min)):
        raise ValueError("times must be positive and finite")
    logs = [math.log(r / e) for r, e in zip(real_min, estimated_min, strict=True)]
    return math.exp(math.fsum(logs) / len(logs))


def error_pct(estimated_min: float, real_min: float) -> float:
    """Signed error of the estimate against the real time, in percent."""
    if real_min <= 0:
        raise ValueError("real time must be positive")
    return (estimated_min - real_min) / real_min * 100.0


def within_limit(errors_pct: Sequence[float], limit_pct: float = LIMIT_PCT) -> bool:
    return bool(errors_pct) and all(abs(e) <= limit_pct for e in errors_pct)


@dataclass(frozen=True)
class Loaded:
    hike: Hike
    route: RouteSummary
    start: datetime
    pace_1_total_min: float


def _read_manifest(manifest: Path) -> str:
    try:
        return manifest.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ManifestError(
            f"{manifest.name} is not UTF-8 text; in Excel save the CSV as "
            "'CSV UTF-8 (Comma delimited)'"
        ) from None


def _use_utf8(out: TextIO) -> None:
    """Hebrew file names must print even when stdout is a cp1252 pipe or file."""
    if isinstance(out, io.TextIOWrapper):
        out.reconfigure(encoding="utf-8")


def load_hike(hike: Hike, base: Path) -> Loaded:
    path = base / hike.gpx_file
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ManifestError(
            f"{hike.gpx_file}: cannot read {path} ({exc.strerror})"
        ) from None
    try:
        route = summarise_gpx(data, path.name)
    except RouteParseError as exc:
        raise ManifestError(f"{hike.gpx_file}: not a usable GPX ({exc})") from None
    if route.elevation_source == "none":
        raise ManifestError(
            f"{hike.gpx_file}: GPX has no elevation; "
            "export it from AllTrails with elevation"
        )
    # Durations do not depend on the zone; estimate only needs an aware start.
    start = datetime.combine(hike.day, hike.start_local, tzinfo=UTC)
    total = estimate(route, start, 1.0, DEFAULT_REST_MIN_PER_HOUR).total_min
    return Loaded(hike, route, start, total)


def run(manifest: Path, out: TextIO) -> int:
    _use_utf8(out)
    if not manifest.is_file():
        out.write(
            f"BAD INPUT: manifest not found: {manifest}\n"
            f"Create it with the columns {', '.join(COLUMNS)} "
            "(see this tool's docstring).\n"
        )
        return EXIT_BAD_INPUT
    try:
        hikes = parse_manifest(_read_manifest(manifest))
        if len(hikes) < MIN_HIKES:
            raise ManifestError(f"need at least {MIN_HIKES} hikes, found {len(hikes)}")
        loaded = [load_hike(h, manifest.parent) for h in hikes]
    except (ManifestError, OSError) as exc:
        out.write(f"BAD INPUT: {exc}\n")
        return EXIT_BAD_INPUT
    real = [item.hike.total_elapsed_min for item in loaded]
    factor = fit_pace_factor(real, [item.pace_1_total_min for item in loaded])
    out.write(
        f"Fitted pace factor (geometric mean of real / estimated): {factor:.4f}\n"
    )
    if not MIN_PACE_FACTOR <= factor <= MAX_PACE_FACTOR:
        out.write(
            f"CHECKPOINT: FAIL - the fitted factor {factor:.4f} is outside "
            f"[{MIN_PACE_FACTOR:g}, {MAX_PACE_FACTOR:g}], so the app cannot set it.\n"
        )
        return EXIT_FAIL
    out.write(f"Rest {DEFAULT_REST_MIN_PER_HOUR:g} min/h; limit +-{LIMIT_PCT:g} %\n\n")
    out.write(
        f"{'hike':<44} {'elevation':>9} {'estimated':>10} {'real':>8} {'error':>8}  "
        "verdict\n"
    )
    errors: list[float] = []
    for item, real_min in zip(loaded, real, strict=True):
        est = estimate(
            item.route, item.start, factor, DEFAULT_REST_MIN_PER_HOUR
        ).total_min
        err = error_pct(est, real_min)
        errors.append(err)
        verdict = "PASS" if abs(err) <= LIMIT_PCT else "FAIL"
        out.write(
            f"{item.hike.gpx_file[:44]:<44} {item.route.elevation_source:>9} "
            f"{est:>10.1f} {real_min:>8.1f} {err:>+7.1f}%  {verdict}\n"
        )
    ok = within_limit(errors)
    out.write(f"\nCHECKPOINT: {'PASS' if ok else 'FAIL'}\n")
    return EXIT_OK if ok else EXIT_FAIL


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) > 1:
            sys.stdout.write("usage: python -m tools.timing_checkpoint [hikes.csv]\n")
            return EXIT_BAD_INPUT
        return run(Path(args[0]) if args else DEFAULT_MANIFEST, sys.stdout)
    except Exception as exc:  # last resort: a crash must never read as a FAIL
        sys.stderr.write(f"INTERNAL ERROR (not a checkpoint result): {exc!r}\n")
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
