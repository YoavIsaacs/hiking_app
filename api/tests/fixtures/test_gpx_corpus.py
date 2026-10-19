"""Guards the GPX corpus: files and expected.json agree, each file is its edge case."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests.fixtures.loader import (
    EXPECTED_FILE,
    GPX_DIR,
    Expected,
    all_fixtures,
    corpus_problems,
    invalid_fixtures,
    load_expected,
    valid_fixtures,
)

GPX_NS = "{http://www.topografix.com/GPX/1/1}"
ALL = all_fixtures()
VALID = valid_fixtures()
INVALID = invalid_fixtures()


def _ids(pairs: list[tuple[Path, Expected]]) -> list[str]:
    return [p.name for p, _ in pairs]


def _count(name: str, tag: str) -> int:
    return len(ET.parse(GPX_DIR / name).getroot().findall(f".//{GPX_NS}{tag}"))


def _blank_entry(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source": "X",
        "original_name": None,
        "derived_from": None,
        "derivation": None,
        "reference_distance_m": 1000,
        "reference_gain_m": 10,
        "has_elevation": True,
        "expected_error": None,
        "segment_gap_m": None,
    }
    return {**base, **over}


def _write_corpus(
    directory: Path, files: list[str], entries: dict[str, dict[str, object]]
) -> None:
    for name in files:
        (directory / name).write_text("<x/>", encoding="utf-8")
    (directory / EXPECTED_FILE).write_text(json.dumps(entries), encoding="utf-8")


# The real corpus.


def test_every_gpx_has_an_entry_and_every_entry_has_a_file() -> None:
    problems = [
        p
        for p in corpus_problems()
        if "no expected.json entry" in p or "entry has no file" in p
    ]
    assert problems == []


@pytest.mark.parametrize(("path", "expected"), VALID, ids=_ids(VALID))
def test_valid_entry_has_reference_distance(path: Path, expected: Expected) -> None:
    assert expected.reference_distance_m is not None, (
        f"{path.name}: reference_distance_m is null"
    )


@pytest.mark.parametrize(("path", "expected"), VALID, ids=_ids(VALID))
def test_valid_entry_with_elevation_has_reference_gain(
    path: Path, expected: Expected
) -> None:
    assert expected.has_elevation is not None, f"{path.name}: has_elevation is null"
    if expected.has_elevation:
        assert expected.reference_gain_m is not None, (
            f"{path.name}: reference_gain_m is null"
        )
    else:
        assert expected.reference_gain_m is None


@pytest.mark.parametrize(("path", "expected"), INVALID, ids=_ids(INVALID))
def test_invalid_entry_has_error_code_and_no_reference_values(
    path: Path, expected: Expected
) -> None:
    assert expected.expected_error == "invalid_gpx"
    assert expected.reference_distance_m is None
    assert expected.reference_gain_m is None


def test_corpus_has_no_other_problems() -> None:
    assert corpus_problems() == []


@pytest.mark.parametrize(("path", "expected"), ALL, ids=_ids(ALL))
def test_entry_provenance_is_consistent(path: Path, expected: Expected) -> None:
    assert (expected.derived_from is None) == (expected.derivation is None)
    assert (expected.original_name is None) == (expected.derived_from is not None)


# The checks themselves fail when they should (synthetic corpora).


def test_loader_rejects_unknown_and_missing_keys(tmp_path: Path) -> None:
    for bad, label in (
        ({**_blank_entry(), "extra": 1}, "unknown"),
        ({k: v for k, v in _blank_entry().items() if k != "source"}, "missing"),
    ):
        (tmp_path / EXPECTED_FILE).write_text(
            json.dumps({"a.gpx": bad}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match=label):
            load_expected(tmp_path)


def test_loader_rejects_wrongly_typed_values(tmp_path: Path) -> None:
    (tmp_path / EXPECTED_FILE).write_text(
        json.dumps({"a.gpx": _blank_entry(reference_distance_m="6342")}),
        encoding="utf-8",
    )
    with pytest.raises(TypeError):
        load_expected(tmp_path)


def test_checker_flags_file_without_entry(tmp_path: Path) -> None:
    _write_corpus(tmp_path, ["a.gpx", "b.gpx"], {"a.gpx": _blank_entry()})
    assert corpus_problems(tmp_path) == ["b.gpx: file has no expected.json entry"]


def test_checker_flags_entry_without_file(tmp_path: Path) -> None:
    _write_corpus(
        tmp_path, ["a.gpx"], {"a.gpx": _blank_entry(), "b.gpx": _blank_entry()}
    )
    assert corpus_problems(tmp_path) == ["b.gpx: expected.json entry has no file"]


def test_checker_flags_valid_entry_without_reference_values(tmp_path: Path) -> None:
    entries = {
        "a.gpx": _blank_entry(reference_distance_m=None),
        "b.gpx": _blank_entry(reference_gain_m=None),
    }
    _write_corpus(tmp_path, ["a.gpx", "b.gpx"], entries)
    assert corpus_problems(tmp_path) == [
        "a.gpx: valid entry has null reference_distance_m",
        "b.gpx: has_elevation but null reference_gain_m",
    ]


def test_checker_allows_null_gain_without_elevation(tmp_path: Path) -> None:
    _write_corpus(
        tmp_path,
        ["a.gpx"],
        {"a.gpx": _blank_entry(reference_gain_m=None, has_elevation=False)},
    )
    assert corpus_problems(tmp_path) == []


def test_checker_flags_invalid_entry_carrying_reference_values(tmp_path: Path) -> None:
    _write_corpus(
        tmp_path, ["a.gpx"], {"a.gpx": _blank_entry(expected_error="invalid_gpx")}
    )
    assert corpus_problems(tmp_path) == [
        "a.gpx: invalid file must not carry reference values"
    ]


# Each fixture really is the edge case it is named for.


def test_corpus_has_nine_fixtures() -> None:
    assert len(ALL) == 9


def test_over_10k_file_has_more_than_10000_points() -> None:
    assert _count("derived-ben-shemen-over-10k-points.gpx", "trkpt") > 10_000


def test_no_ele_file_has_no_ele_elements_but_still_has_points() -> None:
    name = "derived-tel-hadid-no-ele.gpx"
    assert _count(name, "ele") == 0
    assert _count(name, "trkpt") > 0
    assert load_expected()[name].has_elevation is False


def test_real_files_have_elevation_on_every_point() -> None:
    for name, e in load_expected().items():
        if e.derived_from is None:
            assert _count(name, "ele") == _count(name, "trkpt") > 0


def test_rte_file_has_rte_and_no_trk() -> None:
    name = "derived-modiin-hills-south-rte.gpx"
    assert _count(name, "rte") == 1
    assert _count(name, "rtept") > 0
    assert _count(name, "trk") == 0


def test_multi_segment_file_has_two_or_more_trkseg_and_records_the_gap() -> None:
    name = "derived-tel-hadid-multi-segment.gpx"
    assert _count(name, "trkseg") >= 2
    gap = load_expected()[name].segment_gap_m
    assert gap is not None
    assert 50 <= gap <= 150


def test_malformed_file_fails_xml_parsing() -> None:
    with pytest.raises(ET.ParseError):
        ET.parse(GPX_DIR / "derived-ben-shemen-truncated.gpx")


def test_kml_file_is_valid_xml_with_a_non_gpx_root() -> None:
    root = ET.parse(GPX_DIR / "derived-modiin-hills-south-kml.gpx").getroot()
    assert re.sub(r"^\{.*\}", "", root.tag) == "kml"
