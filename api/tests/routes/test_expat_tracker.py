"""The expat allocation tracker (ADR 0004 round-3 amendment, items 28-30 and 36).

* the API exists on the running interpreter, and ``require_alloc_tracker`` refuses to
  start without it (3.11);
* ``_new_parser`` sets both tracker values (3.1 step 3), proved by behaviour;
* a tracker refusal is HTTP 422 ``invalid_gpx`` "The file is too complex to parse."
  while a malformed file keeps its message (3.1 step 5);
* the 1 MiB round-3 shape through ``parse_gpx`` and through the real router;
* legitimate files are unaffected.
"""

import tracemalloc
from collections.abc import Callable
from pathlib import Path
from xml.parsers import expat
from xml.parsers.expat import ExpatError, errors

import pytest
from fastapi.testclient import TestClient

from app.routes.errors import InvalidGpx, TooManyPoints
from app.routes.params import (
    EXPAT_ALLOC_ACTIVATION_BYTES,
    EXPAT_ALLOC_MAX_AMPLIFICATION,
    MAX_CAPTURED_TEXT_CHARS,
)
from app.routes.parse import (
    TOO_COMPLEX_MESSAGE,
    _invalid_gpx_from,
    _new_parser,
    parse_gpx,
    require_alloc_tracker,
)
from app.routes.summary import summarise_gpx
from tests.fixtures.loader import fixture_params, valid_fixtures
from tests.routes.gpx_builders import gpx_bytes, out_and_back
from tests.routes.hostile_shapes import (
    KIB,
    MIB,
    TWO_POINTS,
    last_json_line,
    prefixed_attribute_burst,
    run_python,
    wpt_with_prefixed_burst,
    xmlns_binding_burst,
)
from tests.routes.http_helpers import URL, assert_error

# typed as returning object so mypy lets the tests assert the None return
require: Callable[..., object] = require_alloc_tracker

# a NotImplementedError is a RuntimeError, so the refusal must be told by its message
REFUSAL = "allocation tracker"
SET_THRESHOLD = "SetAllocTrackerActivationThreshold"
SET_AMPLIFICATION = "SetAllocTrackerMaximumAmplification"
NO_MEMORY = errors.codes[errors.XML_ERROR_NO_MEMORY]
AMPLIFICATION = errors.codes[errors.XML_ERROR_AMPLIFICATION_LIMIT_BREACH]

# ~1 MiB with a 1 KiB URI: about 100k distinct attributes, ~100 MiB of expanded names
# without the tracker (ADR "How it is tested").
ROUND3_1MIB = prefixed_attribute_burst(1 * MIB, 1 * KIB)
VALID = gpx_bytes([out_and_back()])


# --- the API exists on this interpreter (may already pass: it only needs 3.12.13+) ---


def test_pyexpat_has_both_alloc_tracker_methods() -> None:
    parser = expat.ParserCreate()
    assert callable(getattr(parser, SET_THRESHOLD, None))
    assert callable(getattr(parser, SET_AMPLIFICATION, None))


def test_expat_is_at_least_2_7_2() -> None:
    assert expat.version_info >= (2, 7, 2)


def test_the_tracker_constants_and_text_cap_are_the_documented_values() -> None:
    assert EXPAT_ALLOC_ACTIVATION_BYTES == 32 * 1024 * 1024
    assert EXPAT_ALLOC_MAX_AMPLIFICATION == 4.0
    assert MAX_CAPTURED_TEXT_CHARS == 65_536


# --- require_alloc_tracker ---


class Both:
    def SetAllocTrackerActivationThreshold(self, threshold: int, /) -> None: ...  # noqa: N802

    def SetAllocTrackerMaximumAmplification(self, factor: float, /) -> None: ...  # noqa: N802


class OnlyThreshold:
    def SetAllocTrackerActivationThreshold(self, threshold: int, /) -> None: ...  # noqa: N802


class OnlyAmplification:
    def SetAllocTrackerMaximumAmplification(self, factor: float, /) -> None: ...  # noqa: N802


class Neither:
    pass


@pytest.mark.parametrize("parser_type", [Neither, OnlyThreshold, OnlyAmplification])
def test_require_alloc_tracker_raises_for_a_parser_type_missing_a_method(
    parser_type: type[object],
) -> None:
    with pytest.raises(RuntimeError, match=REFUSAL) as excinfo:
        require_alloc_tracker(parser_type=parser_type, expat_version=(2, 8, 5))
    assert not isinstance(excinfo.value, NotImplementedError)


@pytest.mark.parametrize("version", [(2, 7, 1), (2, 6, 4), (1, 99, 99), (0, 0, 0)])
def test_require_alloc_tracker_raises_for_an_expat_below_2_7_2(
    version: tuple[int, int, int],
) -> None:
    with pytest.raises(RuntimeError, match=REFUSAL) as excinfo:
        require_alloc_tracker(parser_type=Both, expat_version=version)
    assert not isinstance(excinfo.value, NotImplementedError)


@pytest.mark.parametrize("version", [(2, 7, 2), (2, 7, 3), (2, 8, 0), (3, 0, 0)])
def test_require_alloc_tracker_accepts_both_methods_at_2_7_2_or_later(
    version: tuple[int, int, int],
) -> None:
    assert require(parser_type=Both, expat_version=version) is None


def test_require_alloc_tracker_accepts_the_real_runtime() -> None:
    assert require() is None
    assert require(type(expat.ParserCreate()), expat.version_info) is None


def test_the_runtime_error_says_what_is_missing() -> None:
    with pytest.raises(RuntimeError, match=REFUSAL) as excinfo:
        require_alloc_tracker(parser_type=Neither, expat_version=(2, 8, 5))
    assert not isinstance(excinfo.value, NotImplementedError)


# --- no tracker, no app: the guard runs at import, through the real import chain ---

IMPORT_UNDER_OLD_EXPAT = """
    import xml.parsers.expat as expat
    expat.version_info = (2, 7, 1)  # parse.py binds its default from this at import
    try:
        import {module}
    except RuntimeError as exc:
        print('{{"outcome": "refused", "message": %r}}' % str(exc))
    else:
        print('{{"outcome": "imported", "message": ""}}')
"""


@pytest.mark.parametrize("module", ["app.routes.parse", "app.main"])
def test_importing_the_parser_or_the_app_fails_on_an_expat_without_the_tracker(
    module: str,
) -> None:
    out = last_json_line(run_python(IMPORT_UNDER_OLD_EXPAT.format(module=module)))
    assert out["outcome"] == "refused", out
    assert "allocation tracker" in str(out["message"])


def test_the_import_guard_is_a_raise_not_an_assert_so_python_dash_o_keeps_it() -> None:
    code = IMPORT_UNDER_OLD_EXPAT.format(module="app.routes.parse")
    out = last_json_line(run_python(code, flags=["-O"]))
    assert out["outcome"] == "refused", out


# --- _new_parser sets both values (behaviourally) ---

# 64 KiB of the round-3 shape: ~9 MB tracked, ratio ~137x; 1 MiB: ~100 MB, > 64 MiB
SMALL_AMPLIFYING = prefixed_attribute_burst(64 * KIB, 1 * KIB)
LARGE_AMPLIFYING = ROUND3_1MIB


def feed(parser: expat.XMLParserType, data: bytes) -> None:
    parser.Parse(data, True)


def test_a_low_threshold_and_low_amplification_make_an_amplifying_document_fail() -> (
    None
):
    parser = _new_parser(alloc_threshold_bytes=1 * MIB, alloc_max_amplification=4.0)
    with pytest.raises(ExpatError) as excinfo:
        feed(parser, SMALL_AMPLIFYING)
    assert excinfo.value.code == NO_MEMORY


def test_the_threshold_value_is_applied_not_left_at_expats_64_mib_default() -> None:
    """At 4x the document is refused once past the threshold. Expat's default
    threshold (64 MiB) would let this ~9 MB parse through."""
    parser = _new_parser(alloc_threshold_bytes=0, alloc_max_amplification=4.0)
    with pytest.raises(ExpatError):
        feed(parser, SMALL_AMPLIFYING)


def test_the_amplification_value_is_applied_not_left_at_expats_100x_default() -> None:
    """The document amplifies ~137x, so expat's default factor (100x) would refuse it
    past a 1 MiB threshold; a huge factor must let it through."""
    parser = _new_parser(alloc_threshold_bytes=1 * MIB, alloc_max_amplification=1e6)
    feed(parser, SMALL_AMPLIFYING)


def test_a_huge_threshold_and_factor_1_let_a_100_mib_document_through() -> None:
    """The threshold is not applied to the wrong setter: past expat's own 64 MiB
    default, a 1 GiB threshold must still allow everything."""
    parser = _new_parser(alloc_threshold_bytes=1024 * MIB, alloc_max_amplification=1.0)
    feed(parser, LARGE_AMPLIFYING)


def test_the_new_parser_is_a_namespace_aware_utf_8_parser_with_ordered_attributes() -> (
    None
):
    parser = _new_parser(
        alloc_threshold_bytes=EXPAT_ALLOC_ACTIVATION_BYTES,
        alloc_max_amplification=EXPAT_ALLOC_MAX_AMPLIFICATION,
    )
    seen: list[tuple[str, list[str]]] = []
    parser.StartElementHandler = lambda name, attrs: seen.append((name, attrs))
    parser.Parse(b'<a xmlns="urn:x" k="v"/>', True)
    assert seen == [("urn:x|a", ["k", "v"])]


# --- the seams on parse_gpx ---


def test_the_seams_pass_through_to_the_parser() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(VALID, alloc_threshold_bytes=0, alloc_max_amplification=1.0)
    assert excinfo.value.message == TOO_COMPLEX_MESSAGE


def test_the_same_small_valid_file_parses_at_the_defaults() -> None:
    assert len(parse_gpx(VALID).points) > 2


# --- error mapping ---


def expat_error(code: int, lineno: int = 1, offset: int = 0) -> ExpatError:
    exc = ExpatError(errors.messages[code])
    exc.code = code
    exc.lineno = lineno
    exc.offset = offset
    return exc


@pytest.mark.parametrize("code", [NO_MEMORY, AMPLIFICATION])
def test_a_resource_refusal_maps_to_the_too_complex_message(code: int) -> None:
    mapped = _invalid_gpx_from(expat_error(code, lineno=3, offset=7))
    assert isinstance(mapped, InvalidGpx)
    assert mapped.message == "The file is too complex to parse."
    assert mapped.message == TOO_COMPLEX_MESSAGE


def test_the_too_complex_message_has_no_line_or_column() -> None:
    message = _invalid_gpx_from(expat_error(NO_MEMORY, lineno=12, offset=34)).message
    assert "12" not in message and "34" not in message


def test_an_ordinary_syntax_error_keeps_the_well_formed_message() -> None:
    mapped = _invalid_gpx_from(
        expat_error(errors.codes[errors.XML_ERROR_SYNTAX], lineno=3, offset=7)
    )
    assert mapped.message == "The file is not well-formed XML (line 3, column 7)."


def test_a_mismatched_tag_through_parse_gpx_keeps_the_well_formed_message() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(b"<gpx><trk></gpx>")
    assert excinfo.value.message.startswith("The file is not well-formed XML (line 1")


def test_the_round_3_shape_is_refused_with_the_too_complex_message() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(ROUND3_1MIB)
    assert excinfo.value.message == TOO_COMPLEX_MESSAGE


def test_expat_reports_a_tracker_refusal_as_no_memory_not_amplification_breach() -> (
    None
):
    """Pins the code observed on expat 2.8.5 / CPython 3.12.15: XML_ERROR_NO_MEMORY
    (code 1, 'out of memory'). The breach code is only a defensive mapping."""
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(ROUND3_1MIB)
    cause = excinfo.value.__cause__
    assert isinstance(cause, ExpatError)
    assert cause.code == NO_MEMORY
    assert cause.code != AMPLIFICATION


def test_the_round_3_shape_is_refused_quickly_and_within_the_memory_bound() -> None:
    parse_gpx(b"<gpx>" + TWO_POINTS + b"</gpx>")  # warm up imports and caches
    tracemalloc.start()
    try:
        with pytest.raises(InvalidGpx):
            parse_gpx(ROUND3_1MIB)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak <= 48 * MIB, peak / MIB


def test_the_xmlns_binding_shape_is_refused_too() -> None:
    doc = xmlns_binding_burst(4 * MIB, 1)
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(doc)
    assert excinfo.value.message == TOO_COMPLEX_MESSAGE


# --- precedence is document order (ADR 3.1 step 5) ---

ROOT_P = b'<gpx xmlns:p="urn:p">'
WPT_BURST = wpt_with_prefixed_burst(512 * KIB)


def test_a_burst_after_the_100_001st_point_gives_too_many_points() -> None:
    four = b"".join(b'<trkpt lat="1" lon="1"/>' for _ in range(4))
    doc = ROOT_P + b"<trk><trkseg>" + four + b"</trkseg></trk>" + WPT_BURST + b"</gpx>"
    with pytest.raises(TooManyPoints):
        parse_gpx(doc, max_points=3)


def test_a_burst_after_a_malformation_gives_the_well_formed_message() -> None:
    doc = ROOT_P + b"<a></b>" + WPT_BURST + b"</gpx>"
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(doc)
    assert excinfo.value.message.startswith("The file is not well-formed XML")


def test_a_burst_before_a_malformation_gives_the_too_complex_message() -> None:
    doc = ROOT_P + WPT_BURST + b"<a></b></gpx>"
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(doc)
    assert excinfo.value.message == TOO_COMPLEX_MESSAGE


# --- through the real wiring: create_app -> router -> summarise_gpx -> parse_gpx ---


def test_the_round_3_shape_posted_is_422_invalid_gpx_too_complex(
    client: TestClient,
) -> None:
    response = client.post(
        URL, files={"file": ("hostile.gpx", ROUND3_1MIB, "application/gpx+xml")}
    )
    body = assert_error(response, 422, "invalid_gpx")
    assert body == {
        "code": "invalid_gpx",
        "message": "The file is too complex to parse.",
        "detail": None,
    }


def test_a_malformed_file_posted_keeps_the_well_formed_message(
    client: TestClient,
) -> None:
    response = client.post(
        URL, files={"file": ("bad.gpx", b"<gpx><trk></gpx>", "application/gpx+xml")}
    )
    body = assert_error(response, 422, "invalid_gpx")
    message = str(body["message"])
    assert message.startswith("The file is not well-formed XML (line 1, column")


def test_a_refusal_is_never_a_500_or_a_413(client: TestClient) -> None:
    response = client.post(
        URL, files={"file": ("hostile.gpx", ROUND3_1MIB, "application/gpx+xml")}
    )
    assert response.status_code not in (413, 500)


# --- legitimate files are unaffected ---

FIXTURES = fixture_params(valid_fixtures())


@pytest.mark.parametrize(("path", "expected"), FIXTURES)
def test_every_valid_fixture_still_returns_200_at_the_default_tracker_values(
    path: Path, expected: object, client: TestClient
) -> None:
    response = client.post(
        URL, files={"file": (path.name, path.read_bytes(), "application/gpx+xml")}
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    ("threshold", "factor"),
    [(8 * MIB, 1.0), (1 * MIB, 2.0)],
    ids=["M_legit", "F_legit"],
)
@pytest.mark.parametrize(("path", "expected"), FIXTURES)
def test_every_valid_fixture_parses_inside_the_adr_legitimate_margins(
    path: Path, expected: object, threshold: int, factor: float
) -> None:
    """ADR 3.13: a quarter of the threshold (8 MiB at factor 1.0) and half the
    production factor (2.0 at 1 MiB) must still accept every legitimate file."""
    data = path.read_bytes()
    assert (
        parse_gpx(data).points
        == parse_gpx(
            data, alloc_threshold_bytes=threshold, alloc_max_amplification=factor
        ).points
    )


def real_shaped_100k_points() -> bytes:
    """100,000 points with ele and time, 6-decimal coordinates: just under 10 MiB."""
    rows = [
        f'<trkpt lat="{31.9 + i * 1e-5:.6f}" lon="{34.9 + i * 1e-5:.6f}">'
        f"<ele>{100 + i % 50}.0</ele><time>2026-03-29T02:00:00Z</time></trkpt>"
        for i in range(100_000)
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{''.join(rows)}</trkseg></trk></gpx>"
    ).encode()


@pytest.fixture(scope="module")
def big_real_file() -> bytes:
    data = real_shaped_100k_points()
    assert 8 * MIB < len(data) < 10 * MIB
    return data


def test_a_real_shaped_100k_point_file_parses_at_the_defaults(
    big_real_file: bytes,
) -> None:
    assert len(parse_gpx(big_real_file).points) == 100_000


def test_a_real_shaped_100k_point_file_is_inside_the_legitimate_margins(
    big_real_file: bytes,
) -> None:
    raw = parse_gpx(
        big_real_file, alloc_threshold_bytes=8 * MIB, alloc_max_amplification=1.0
    )
    assert len(raw.points) == 100_000


def test_a_real_shaped_100k_point_file_posted_is_200(
    client: TestClient, big_real_file: bytes
) -> None:
    response = client.post(
        URL, files={"file": ("big.gpx", big_real_file, "application/gpx+xml")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["point_count_original"] == 100_000


# --- the pipeline entry point maps the refusal like any invalid file ---


def test_summarise_gpx_raises_invalid_gpx_with_the_too_complex_message() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        summarise_gpx(ROUND3_1MIB, "hostile.gpx")
    assert excinfo.value.message == TOO_COMPLEX_MESSAGE
