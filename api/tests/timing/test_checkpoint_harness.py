"""tools/timing_checkpoint.py: fit, error and manifest parsing on synthetic data.

The manager's real hikes are uncommitted; nothing here reads them.
"""

import io
import math
from datetime import date, time
from pathlib import Path

import pytest

from tools import timing_checkpoint as cp
from tools.timing_checkpoint import (
    ManifestError,
    error_pct,
    fit_pace_factor,
    parse_manifest,
    run,
    within_limit,
)

HEADER = "gpx_file,date,start_time_local,total_elapsed_min\n"


def csv_text(*rows: str) -> str:
    return HEADER + "".join(r + "\n" for r in rows)


# ---- fit / error ----


def test_fit_is_the_geometric_mean_of_ratios() -> None:
    assert fit_pace_factor([200.0, 50.0], [100.0, 100.0]) == pytest.approx(1.0)
    assert fit_pace_factor([120.0, 240.0], [100.0, 100.0]) == pytest.approx(
        math.sqrt(1.2 * 2.4)
    )


def test_fit_of_identical_ratios_is_that_ratio() -> None:
    assert fit_pace_factor([130.0, 260.0, 65.0], [100.0, 200.0, 50.0]) == pytest.approx(
        1.3
    )


@pytest.mark.parametrize(
    ("real", "est"),
    [
        ([], []),
        ([1.0], [1.0, 2.0]),
        ([0.0], [1.0]),
        ([1.0], [0.0]),
        ([-1.0], [1.0]),
        ([math.nan], [1.0]),
        ([1.0], [math.inf]),
    ],
)
def test_fit_rejects_empty_mismatched_or_non_positive_input(
    real: list[float], est: list[float]
) -> None:
    with pytest.raises(ValueError):
        fit_pace_factor(real, est)


def test_errors_after_the_fit_balance_in_log_space() -> None:
    real, est = [90.0, 110.0, 150.0, 70.0, 100.0], [100.0, 100.0, 100.0, 100.0, 100.0]
    f = fit_pace_factor(real, est)
    logs = [math.log(e * f / r) for e, r in zip(est, real, strict=True)]
    assert sum(logs) == pytest.approx(0.0, abs=1e-12)


def test_error_pct_is_signed_relative_to_real() -> None:
    assert error_pct(120.0, 100.0) == pytest.approx(20.0)
    assert error_pct(80.0, 100.0) == pytest.approx(-20.0)
    assert error_pct(100.0, 100.0) == 0.0


def test_error_pct_rejects_non_positive_real() -> None:
    with pytest.raises(ValueError):
        error_pct(10.0, 0.0)


def test_within_limit_is_inclusive_of_twenty_percent() -> None:
    assert within_limit([20.0, -20.0, 0.0])
    assert not within_limit([20.01])
    assert not within_limit([-20.01, 1.0])
    assert not within_limit([])


# ---- manifest ----


def test_parse_manifest_reads_every_column() -> None:
    hikes = parse_manifest(
        csv_text("a.gpx,2026-03-14,07:30,95", "b.gpx,2026-04-01,06:05,210.5")
    )
    assert hikes[0] == cp.Hike("a.gpx", date(2026, 3, 14), time(7, 30), 95.0)
    assert hikes[1] == cp.Hike("b.gpx", date(2026, 4, 1), time(6, 5), 210.5)


def test_parse_manifest_accepts_bom_blank_lines_spaces_and_hebrew_names() -> None:
    text = "﻿" + HEADER + "\n תל_חדיד.gpx , 2026-03-14 , 07:30 , 95 \n\n"
    assert parse_manifest(text)[0].gpx_file == "תל_חדיד.gpx"


def test_parse_manifest_ignores_extra_columns() -> None:
    text = HEADER.strip() + ",notes\na.gpx,2026-03-14,07:30,95,windy\n"
    assert len(parse_manifest(text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "",
        HEADER,
        "gpx_file,date,start_time_local\na.gpx,2026-03-14,07:30\n",
        csv_text(",2026-03-14,07:30,95"),
        csv_text("a.gpx,14/03/2026,07:30,95"),
        csv_text("a.gpx,2026-02-30,07:30,95"),
        csv_text("a.gpx,2026-03-14,7.30,95"),
        csv_text("a.gpx,2026-03-14,25:00,95"),
        csv_text("a.gpx,2026-03-14,07:30,1h35"),
        csv_text("a.gpx,2026-03-14,07:30,0"),
        csv_text("a.gpx,2026-03-14,07:30,-5"),
        csv_text("a.gpx,2026-03-14,07:30,nan"),
        csv_text("a.gpx,2026-03-14,07:30,inf"),
        csv_text("a.gpx,2026-03-14,07:30"),
    ],
)
def test_parse_manifest_rejects_bad_input(text: str) -> None:
    with pytest.raises(ManifestError):
        parse_manifest(text)


def test_manifest_error_names_the_row() -> None:
    with pytest.raises(ManifestError, match="row 3"):
        parse_manifest(csv_text("a.gpx,2026-03-14,07:30,95", "b.gpx,oops,07:30,95"))


# ---- run(): exit codes and output ----


def write_flat_gpx(path: Path) -> None:
    pts = "".join(
        f'<trkpt lat="{32.0 + i * 0.0009:.6f}" lon="34.0"><ele>100</ele></trkpt>'
        for i in range(25)
    )
    path.write_text(
        '<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>t</name><trkseg>{pts}</trkseg></trk></gpx>",
        encoding="utf-8",
    )


def manifest_with(tmp_path: Path, reals: list[str]) -> Path:
    write_flat_gpx(tmp_path / "flat.gpx")
    rows = [f"flat.gpx,2026-03-1{i + 1},07:30,{r}" for i, r in enumerate(reals)]
    path = tmp_path / "hikes.csv"
    path.write_text(csv_text(*rows), encoding="utf-8")
    return path


def test_run_passes_and_prints_the_fitted_factor_when_all_within_limit(
    tmp_path: Path,
) -> None:
    out = io.StringIO()
    code = run(manifest_with(tmp_path, ["80"] * 5), out)
    text = out.getvalue()
    assert code == 0
    assert "Fitted pace factor" in text
    assert text.count("PASS") == 6  # five hikes and the final verdict
    assert "FAIL" not in text
    assert "flat.gpx" in text


def test_run_fails_with_exit_1_when_one_hike_is_outside_twenty_percent(
    tmp_path: Path,
) -> None:
    out = io.StringIO()
    code = run(manifest_with(tmp_path, ["80", "80", "80", "80", "200"]), out)
    assert code == 1
    assert "FAIL" in out.getvalue()
    assert "CHECKPOINT: FAIL" in out.getvalue()


def test_run_with_a_missing_gpx_is_bad_input(tmp_path: Path) -> None:
    path = tmp_path / "hikes.csv"
    path.write_text(
        csv_text(*[f"nope{i}.gpx,2026-03-14,07:30,90" for i in range(5)]),
        encoding="utf-8",
    )
    out = io.StringIO()
    assert run(path, out) == 2
    assert "BAD INPUT" in out.getvalue()


def test_run_with_a_non_gpx_file_is_bad_input(tmp_path: Path) -> None:
    path = manifest_with(tmp_path, ["80"] * 5)
    (tmp_path / "flat.gpx").write_text("not xml", encoding="utf-8")
    assert run(path, io.StringIO()) == 2


def test_run_with_a_missing_manifest_is_bad_input(tmp_path: Path) -> None:
    out = io.StringIO()
    assert run(tmp_path / "absent.csv", out) == 2
    assert "BAD INPUT" in out.getvalue()


def test_run_with_fewer_than_five_hikes_is_bad_input(tmp_path: Path) -> None:
    assert run(manifest_with(tmp_path, ["80"] * 4), io.StringIO()) == 2


def test_run_with_a_bad_row_is_bad_input(tmp_path: Path) -> None:
    assert (
        run(manifest_with(tmp_path, ["80", "80", "80", "80", "soon"]), io.StringIO())
        == 2
    )


def test_main_with_too_many_arguments_is_bad_input() -> None:
    assert cp.main(["a.csv", "b.csv"]) == 2


def test_main_takes_the_manifest_path_from_argv(tmp_path: Path) -> None:
    assert cp.main([str(manifest_with(tmp_path, ["80"] * 5))]) == 0


def test_default_manifest_is_under_docs_maps_hikes() -> None:
    assert cp.DEFAULT_MANIFEST.parts[-4:] == ("docs", "maps", "hikes", "hikes.csv")
