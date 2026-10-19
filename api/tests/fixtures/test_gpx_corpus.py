"""Guards the GPX corpus: files and expected.json agree, each file is its edge case."""

import codecs
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests.fixtures.loader import (
    EDGE_CASES,
    EXPECTED_FILE,
    GPX_DIR,
    Expected,
    all_fixtures,
    corpus_problems,
    edge_case_fixtures,
    fixture_params,
    invalid_fixtures,
    load_expected,
    valid_fixtures,
)

GPX_NS = "{http://www.topografix.com/GPX/1/1}"
ALL = fixture_params(all_fixtures())
VALID = fixture_params(valid_fixtures())
INVALID = fixture_params(invalid_fixtures())

# Roadmap edge cases with no fixture yet because the manager deferred them
# (see "Deviation" in docs/steps/1.1.md). Adding the file removes the case from
# here: test_every_roadmap_edge_case_has_a_fixture_except_the_deferred_ones fails
# until this set is emptied of it.
DEFERRED_BY_MANAGER = frozenset({"out_and_back"})
ROADMAP_EDGE_CASES = frozenset(
    {
        "loop",
        "out_and_back",
        "no_elevation",
        "over_10k_points",
        "rte",
        "multi_segment",
        "malformed",
    }
)


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
        "edge_cases": [],
        "is_loop": True,
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


@pytest.mark.parametrize(("path", "expected"), VALID)
def test_valid_entry_has_reference_distance(path: Path, expected: Expected) -> None:
    assert expected.reference_distance_m is not None, (
        f"{path.name}: reference_distance_m is null"
    )


@pytest.mark.parametrize(("path", "expected"), VALID)
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


@pytest.mark.parametrize(("path", "expected"), INVALID)
def test_invalid_entry_has_error_code_and_no_reference_values(
    path: Path, expected: Expected
) -> None:
    assert expected.expected_error == "invalid_gpx"
    assert expected.reference_distance_m is None
    assert expected.reference_gain_m is None


def test_corpus_has_no_other_problems() -> None:
    assert corpus_problems() == []


@pytest.mark.parametrize(("path", "expected"), ALL)
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


def test_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    entry = json.dumps(_blank_entry())
    (tmp_path / EXPECTED_FILE).write_text(
        f'{{"a.gpx": {entry}, "a.gpx": {entry}}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_expected(tmp_path)


def test_checker_flags_stray_non_gpx_file(tmp_path: Path) -> None:
    _write_corpus(tmp_path, ["a.gpx"], {"a.gpx": _blank_entry()})
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.gpx.bak").write_text("<x/>", encoding="utf-8")
    assert corpus_problems(tmp_path) == [
        "b.gpx.bak: unexpected non-.gpx file in corpus",
        "notes.txt: unexpected non-.gpx file in corpus",
    ]


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


def _only(case: str) -> tuple[Path, Expected]:
    fixtures = edge_case_fixtures(case)
    assert len(fixtures) == 1, f"{case}: expected exactly one fixture"
    return fixtures[0]


def test_corpus_has_nine_fixtures() -> None:
    assert len(ALL) == 9


def test_every_roadmap_edge_case_has_a_fixture_except_the_deferred_ones() -> None:
    covered = {case for case in ROADMAP_EDGE_CASES if edge_case_fixtures(case)}
    assert covered == ROADMAP_EDGE_CASES - DEFERRED_BY_MANAGER


def test_edge_case_vocabulary_matches_the_roadmap_plus_not_gpx() -> None:
    assert set(EDGE_CASES) == {*ROADMAP_EDGE_CASES, "not_gpx"}


def test_edge_case_fixtures_rejects_an_unknown_case() -> None:
    with pytest.raises(ValueError, match="unknown edge case"):
        edge_case_fixtures("zigzag")


def test_over_10k_file_has_more_than_10000_points() -> None:
    path, _ = _only("over_10k_points")
    assert _count(path.name, "trkpt") > 10_000


def test_no_ele_file_has_no_ele_elements_but_still_has_points() -> None:
    path, expected = _only("no_elevation")
    assert _count(path.name, "ele") == 0
    assert _count(path.name, "trkpt") > 0
    assert expected.has_elevation is False


def test_real_files_have_elevation_on_every_point() -> None:
    for name, e in load_expected().items():
        if e.derived_from is None:
            assert _count(name, "ele") == _count(name, "trkpt") > 0


def test_rte_file_has_rte_and_no_trk() -> None:
    path, _ = _only("rte")
    assert _count(path.name, "rte") == 1
    assert _count(path.name, "rtept") > 0
    assert _count(path.name, "trk") == 0


def test_multi_segment_file_has_two_or_more_trkseg_and_records_the_gap() -> None:
    path, expected = _only("multi_segment")
    assert _count(path.name, "trkseg") >= 2
    assert expected.segment_gap_m is not None
    assert 20 <= expected.segment_gap_m <= 50


def test_malformed_file_fails_xml_parsing() -> None:
    path, _ = _only("malformed")
    with pytest.raises(ET.ParseError):
        ET.parse(path)


def test_kml_file_is_valid_xml_with_a_non_gpx_root() -> None:
    path, _ = _only("not_gpx")
    root = ET.parse(path).getroot()
    assert re.sub(r"^\{.*\}", "", root.tag) == "kml"


def test_only_real_files_and_their_valid_children_are_loops() -> None:
    for name, e in load_expected().items():
        assert (e.is_loop is None) == (e.expected_error is not None), name
        if e.expected_error is None:
            assert e.is_loop is True, name


def test_loader_rejects_unknown_edge_case_and_non_object_entry(tmp_path: Path) -> None:
    for entry, error in (
        (_blank_entry(edge_cases=["zigzag"]), ValueError),
        (_blank_entry(edge_cases="loop"), TypeError),
        ("not an object", TypeError),
    ):
        (tmp_path / EXPECTED_FILE).write_text(
            json.dumps({"a.gpx": entry}), encoding="utf-8"
        )
        with pytest.raises(error):
            load_expected(tmp_path)


# Each derived file really is its parent, point for point (no rounding drift).

Point = tuple[str, str, str | None]  # lat text, lon text, ele text


def _points(name: str, tag: str = "trkpt") -> list[Point]:
    root = ET.parse(GPX_DIR / name).getroot()
    out: list[Point] = []
    for pt in root.iter(f"{GPX_NS}{tag}"):
        ele = pt.find(f"{GPX_NS}ele")
        out.append(
            (pt.attrib["lat"], pt.attrib["lon"], None if ele is None else ele.text)
        )
    return out


def _segments(name: str) -> list[list[Point]]:
    root = ET.parse(GPX_DIR / name).getroot()
    result: list[list[Point]] = []
    for seg in root.iter(f"{GPX_NS}trkseg"):
        pts: list[Point] = []
        for pt in seg.findall(f"{GPX_NS}trkpt"):
            ele = pt.find(f"{GPX_NS}ele")
            pts.append(
                (pt.attrib["lat"], pt.attrib["lon"], None if ele is None else ele.text)
            )
        result.append(pts)
    return result


TEL_HADID = "alltrails-tel-hadid-loop.gpx"
BEN_SHEMEN = "alltrails-ben-shemen-hertzl-singletrack.gpx"
MODIIN = "alltrails-modiin-hills-south-double-loop.gpx"
# Recorded in the multi-segment derivation text: first segment keeps 400 points,
# the next 4 parent points are dropped, the rest form the second segment.
SEG_SPLIT = 400
SEG_DROPPED = 4
ELE = 2  # index of the elevation in a Point


def test_no_ele_file_has_the_parents_lat_lon_sequence() -> None:
    path, expected = _only("no_elevation")
    assert expected.derived_from == TEL_HADID
    assert [(a, b) for a, b, _ in _points(path.name)] == [
        (a, b) for a, b, _ in _points(TEL_HADID)
    ]


def test_rte_file_has_the_parents_points_and_elevations() -> None:
    path, expected = _only("rte")
    assert expected.derived_from == MODIIN
    assert _points(path.name, "rtept") == _points(MODIIN)


def test_multi_segment_file_is_the_parent_minus_exactly_the_dropped_range() -> None:
    path, expected = _only("multi_segment")
    assert expected.derived_from == TEL_HADID
    parent = _points(TEL_HADID)
    first, second = _segments(path.name)
    assert first == parent[:SEG_SPLIT]
    assert second == parent[SEG_SPLIT + SEG_DROPPED :]


def test_over_10k_file_keeps_every_14th_parent_point_and_interpolates_between() -> None:
    path, expected = _only("over_10k_points")
    assert expected.derived_from == BEN_SHEMEN
    parent = _points(BEN_SHEMEN)
    dense = _points(path.name)
    steps = 14
    assert len(dense) == (len(parent) - 1) * steps + 1
    for i, (lat, lon, ele) in enumerate(parent):
        assert dense[i * steps][:2] == (lat, lon)
        assert ele is not None
        dense_ele = dense[i * steps][2]
        assert dense_ele is not None
        assert float(dense_ele) == pytest.approx(float(ele), abs=0.005)
    for i in range(len(parent) - 1):
        for k in range(1, steps):
            t = k / steps
            got = dense[i * steps + k]
            for j, (g, a, b) in enumerate(
                zip(got, parent[i], parent[i + 1], strict=True)
            ):
                assert g is not None and a is not None and b is not None
                want = float(a) + (float(b) - float(a)) * t
                tol = 0.005 if j == ELE else 0.000001
                assert float(g) == pytest.approx(want, abs=tol + 1e-9)


def test_truncated_file_is_a_byte_prefix_of_its_parent_plus_a_newline() -> None:
    path, expected = _only("malformed")
    assert expected.derived_from == BEN_SHEMEN
    parent = (GPX_DIR / BEN_SHEMEN).read_bytes()
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert len(raw) > 1000
    assert parent.startswith(raw[:-1])
    assert len(raw) - 1 < len(parent)


# Reference values, inheritance and Hebrew names in the real corpus.


def test_derived_entries_inherit_parent_reference_values() -> None:
    entries = load_expected()
    for name, e in entries.items():
        if e.derived_from is None or e.expected_error is not None:
            continue
        parent = entries[e.derived_from]
        assert e.reference_distance_m == parent.reference_distance_m, name
        if e.has_elevation:
            assert e.reference_gain_m == parent.reference_gain_m, name


def test_real_files_carry_manager_supplied_alltrails_values() -> None:
    entries = load_expected()
    got = {
        n: (e.reference_distance_m, e.reference_gain_m)
        for n, e in entries.items()
        if e.derived_from is None
    }
    assert got == {
        "alltrails-modiin-hills-south-double-loop.gpx": (8500, 198),
        "alltrails-ben-shemen-hertzl-singletrack.gpx": (10600, 200),
        "alltrails-tel-hadid-loop.gpx": (6400, 103),
    }


def test_hebrew_original_names_round_trip_as_nfc_utf8_without_bom() -> None:
    raw = (GPX_DIR / EXPECTED_FILE).read_bytes()
    assert not raw.startswith(codecs.BOM_UTF8)
    names = [e.original_name for e in load_expected().values() if e.original_name]
    assert len(names) == 3
    for n in names:
        assert unicodedata.normalize("NFC", n) == n
        assert any("֐" <= c <= "׿" for c in n)
