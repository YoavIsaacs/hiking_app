"""Loader for the GPX test corpus in ``tests/fixtures/gpx/``.

Use ``valid_fixtures()`` / ``invalid_fixtures()`` to parametrise tests.
``corpus_problems()`` is the consistency check the corpus test runs; it takes a
directory so it can be tested against synthetic corpora.
"""

import json
from dataclasses import dataclass
from pathlib import Path

GPX_DIR = Path(__file__).parent / "gpx"
EXPECTED_FILE = "expected.json"
EXPECTED_KEYS = frozenset(
    {
        "source",
        "original_name",
        "derived_from",
        "derivation",
        "reference_distance_m",
        "reference_gain_m",
        "has_elevation",
        "expected_error",
        "segment_gap_m",
    }
)


@dataclass(frozen=True)
class Expected:
    """What a source app (or the derivation) says about a fixture; None = unknown."""

    source: str
    original_name: str | None
    derived_from: str | None
    derivation: str | None
    reference_distance_m: float | None
    reference_gain_m: float | None
    has_elevation: bool | None
    expected_error: str | None
    segment_gap_m: float | None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | type(None)):
        raise TypeError(f"expected a number or null, got {value!r}")
    return None if value is None else float(value)


def _text(value: object) -> str | None:
    if not isinstance(value, str | type(None)):
        raise TypeError(f"expected a string or null, got {value!r}")
    return value


def _flag(value: object) -> bool | None:
    if not isinstance(value, bool | type(None)):
        raise TypeError(f"expected a boolean or null, got {value!r}")
    return value


def _build(entry: dict[str, object]) -> Expected:
    source = _text(entry["source"])
    if source is None:
        raise TypeError("source must not be null")
    return Expected(
        source=source,
        original_name=_text(entry["original_name"]),
        derived_from=_text(entry["derived_from"]),
        derivation=_text(entry["derivation"]),
        reference_distance_m=_number(entry["reference_distance_m"]),
        reference_gain_m=_number(entry["reference_gain_m"]),
        has_elevation=_flag(entry["has_elevation"]),
        expected_error=_text(entry["expected_error"]),
        segment_gap_m=_number(entry["segment_gap_m"]),
    )


def load_expected(directory: Path = GPX_DIR) -> dict[str, Expected]:
    """``expected.json`` entries by file name; raises on unknown or missing keys."""
    raw = json.loads((directory / EXPECTED_FILE).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"{EXPECTED_FILE} must be a JSON object keyed by file name")
    result: dict[str, Expected] = {}
    for name, entry in raw.items():
        keys = set(entry)
        if keys != EXPECTED_KEYS:
            missing, unknown = (
                sorted(EXPECTED_KEYS - keys),
                sorted(keys - EXPECTED_KEYS),
            )
            raise ValueError(f"{name}: missing keys {missing}, unknown keys {unknown}")
        result[name] = _build(entry)
    return result


def all_fixtures(directory: Path = GPX_DIR) -> list[tuple[Path, Expected]]:
    return [
        (directory / name, expected)
        for name, expected in sorted(load_expected(directory).items())
    ]


def valid_fixtures(directory: Path = GPX_DIR) -> list[tuple[Path, Expected]]:
    return [(p, e) for p, e in all_fixtures(directory) if e.expected_error is None]


def invalid_fixtures(directory: Path = GPX_DIR) -> list[tuple[Path, Expected]]:
    return [(p, e) for p, e in all_fixtures(directory) if e.expected_error is not None]


def corpus_problems(directory: Path = GPX_DIR) -> list[str]:
    """Every way the corpus and ``expected.json`` disagree; empty means consistent."""
    entries = load_expected(directory)
    files = {p.name for p in directory.glob("*.gpx")}
    problems = [
        f"{n}: file has no expected.json entry" for n in sorted(files - entries.keys())
    ]
    problems += [
        f"{n}: expected.json entry has no file" for n in sorted(entries.keys() - files)
    ]
    for name, e in sorted(entries.items()):
        problems += (
            _invalid_problems(name, e)
            if e.expected_error is not None
            else _valid_problems(name, e)
        )
        if e.derived_from is not None and e.derived_from not in entries:
            problems.append(f"{name}: derived_from {e.derived_from} is not an entry")
    return problems


def _invalid_problems(name: str, e: Expected) -> list[str]:
    if e.reference_distance_m is not None or e.reference_gain_m is not None:
        return [f"{name}: invalid file must not carry reference values"]
    return []


def _valid_problems(name: str, e: Expected) -> list[str]:
    problems: list[str] = []
    if e.reference_distance_m is None:
        problems.append(f"{name}: valid entry has null reference_distance_m")
    if e.has_elevation is None:
        problems.append(f"{name}: valid entry has null has_elevation")
    if e.has_elevation and e.reference_gain_m is None:
        problems.append(f"{name}: has_elevation but null reference_gain_m")
    return problems
