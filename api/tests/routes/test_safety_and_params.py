"""XML attack payloads, the expat floor and ParseParams validation (ADR 0004)."""

import math
import pyexpat
from pathlib import Path

import pytest

from app.routes.errors import InvalidGpx
from app.routes.params import MAX_SUMMARY_POINTS, ParseParams
from app.routes.summary import summarise_gpx
from tests.routes.gpx_builders import gpx_bytes, straight_line

SECRET = "TOP-SECRET-CONTENT-7f3a9c"


def _expat_version() -> tuple[int, ...]:
    return tuple(
        int(n) for n in pyexpat.EXPAT_VERSION.removeprefix("expat_").split(".")
    )


def test_expat_is_at_least_2_6_0() -> None:
    assert _expat_version() >= (2, 6, 0)


def _doc(doctype: str, body_text: str = "&x;") -> bytes:
    return (
        f'<?xml version="1.0"?>{doctype}<gpx version="1.1" creator="t"><metadata>'
        f"<name>{body_text}</name></metadata><trk><trkseg>"
        '<trkpt lat="1" lon="1"/><trkpt lat="1.001" lon="1"/></trkseg></trk></gpx>'
    ).encode()


def _billion_laughs() -> bytes:
    entities = '<!ENTITY a0 "lol">' + "".join(
        f'<!ENTITY a{i} "{f"&a{i - 1};" * 10}">' for i in range(1, 10)
    )
    return _doc(f"<!DOCTYPE gpx [{entities}]>", "&a9;")


def test_xxe_file_entity_is_rejected_and_the_file_content_never_leaks(
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text(SECRET, encoding="utf-8")
    payload = _doc(f'<!DOCTYPE gpx [<!ENTITY x SYSTEM "{secret_file.as_uri()}">]>')
    with pytest.raises(InvalidGpx) as excinfo:
        summarise_gpx(payload, None)
    assert SECRET not in str(excinfo.value)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_billion_laughs(), id="billion-laughs"),
        pytest.param(
            _doc('<!DOCTYPE gpx SYSTEM "http://127.0.0.1:9/evil.dtd">', "x"),
            id="external-dtd",
        ),
        pytest.param(
            _doc('<!DOCTYPE gpx [<!ENTITY x "plain">]>'), id="internal-entity"
        ),
        pytest.param(_doc("<!DOCTYPE gpx>", "x"), id="empty-doctype"),
        pytest.param(
            _doc("<!DOCTYPE gpx [<!ELEMENT gpx ANY>]>", "x"),
            id="internal-subset-no-entity",
        ),
        pytest.param(
            _doc(
                '<!DOCTYPE gpx [<!ENTITY % p SYSTEM "http://127.0.0.1:9/p">%p;]>', "x"
            ),
            id="parameter-entity",
        ),
    ],
)
def test_any_doctype_is_invalid_gpx(payload: bytes) -> None:
    with pytest.raises(InvalidGpx):
        summarise_gpx(payload, None)


def test_a_doctype_after_a_bom_is_still_rejected() -> None:
    with pytest.raises(InvalidGpx):
        summarise_gpx(b"\xef\xbb\xbf" + _billion_laughs(), None)


def test_a_one_megabyte_comment_in_the_prolog_is_cheap_and_accepted() -> None:
    pts = straight_line(3)
    data = gpx_bytes([pts])
    data = data.replace(b"?><gpx", b"?><!--" + b"c" * 1_000_000 + b"--><gpx", 1)
    assert summarise_gpx(data, None).point_count_original == 3


# --- ParseParams ---------------------------------------------------------------------


def test_default_params_are_valid() -> None:
    params = ParseParams()
    assert params.max_points == MAX_SUMMARY_POINTS
    assert params.resample_step_m > 0
    assert params.smoothing_window_m >= 0
    assert params.gain_threshold_m >= 0


def test_boundary_values_are_valid() -> None:
    ParseParams(smoothing_window_m=0.0, gain_threshold_m=0.0, max_points=3)
    ParseParams(max_points=MAX_SUMMARY_POINTS)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resample_step_m": 0.0},
        {"resample_step_m": -1.0},
        {"resample_step_m": math.nan},
        {"resample_step_m": math.inf},
        {"max_resample_points": 0},
        {"max_resample_points": -5},
        {"smoothing_window_m": -0.1},
        {"smoothing_window_m": math.nan},
        {"smoothing_window_m": math.inf},
        {"gain_threshold_m": -0.1},
        {"gain_threshold_m": math.nan},
        {"gain_threshold_m": math.inf},
        {"loop_threshold_m": -1.0},
        {"loop_threshold_m": math.nan},
        {"max_points": 2},
        {"max_points": 0},
        {"max_points": -1},
        {"max_points": MAX_SUMMARY_POINTS + 1},
    ],
    ids=lambda kw: ",".join(f"{k}={v}" for k, v in kw.items()),
)
def test_nonsense_params_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        ParseParams(**kwargs)  # type: ignore[arg-type]  # parametrised kwargs mix int and float
