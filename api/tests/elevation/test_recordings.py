"""The recorded Open-Meteo responses are what ADR 0005 section 7 says they are.

These guard the oracle: a recording that drifted from its parent GPX, or a raw body that
no longer matches the table, would make every backfill test meaningless.
"""

import json
import re

import pytest

from app.clients.elevation import parse_elevations
from app.routes.parse import drop_consecutive_duplicates, parse_gpx
from tests.elevation_support import (
    PARENTS,
    RECORDED_DIR,
    Recording,
    load_recording,
    pair_of,
)
from tests.fixtures.loader import GPX_DIR

META_KEYS = {
    "source_fixture",
    "recorded_at",
    "endpoint",
    "command",
    "notes",
    "git_sha",
    "coord_decimals",
    "docs_checked",
    "requests",
    "points",
}


@pytest.fixture(params=PARENTS)
def recording(request: pytest.FixtureRequest) -> Recording:
    stem: str = request.param
    return load_recording(stem)


def test_the_metadata_has_exactly_the_documented_keys(recording: Recording) -> None:
    assert set(recording.meta) == META_KEYS
    assert recording.meta["source_fixture"] == f"{recording.stem}.gpx"
    assert recording.meta["endpoint"] == "https://api.open-meteo.com/v1/elevation"
    assert recording.meta["coord_decimals"] == 5
    assert (
        recording.meta["docs_checked"] == "https://open-meteo.com/en/docs/elevation-api"
    )
    assert re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(recording.meta["recorded_at"])
    )
    assert re.fullmatch(r"[0-9a-f]{40}", str(recording.meta["git_sha"]))
    assert "record.py" in str(recording.meta["command"])


def test_there_is_one_point_per_deduplicated_point_of_the_parent(
    recording: Recording,
) -> None:
    data = (GPX_DIR / f"{recording.stem}.gpx").read_bytes()
    points = drop_consecutive_duplicates(parse_gpx(data).points)
    recorded = recording.meta["points"]
    assert isinstance(recorded, list)
    assert [(p["lat"], p["lon"]) for p in recorded] == [(q.lat, q.lon) for q in points]
    assert [p["sent"] for p in recorded] == [
        ",".join(pair_of(q.lat, q.lon)) for q in points
    ]


def test_every_request_is_a_200_batch_of_at_most_100_with_a_raw_body(
    recording: Recording,
) -> None:
    requests = recording.meta["requests"]
    assert isinstance(requests, list)
    sizes: list[int] = []
    for k, request in enumerate(requests):
        assert request["status"] == 200
        assert request["raw"] == f"raw/{recording.stem}-{k}.json"
        assert request["date_header"]
        lats = request["url"].split("latitude=")[1].split("&")[0].split(",")
        sizes.append(len(lats))
    assert all(1 <= n <= 100 for n in sizes)
    assert sum(sizes) == len(recording.meta["points"])  # type: ignore[arg-type]  # JSON list
    assert all(n == 100 for n in sizes[:-1])
    assert len(requests) <= 21  # about 21 calls in all, well inside the free tier


def test_the_raw_bodies_match_the_table_in_order(recording: Recording) -> None:
    from_raw = [
        v for body in recording.raw_bodies for v in json.loads(body)["elevation"]
    ]
    from_table = [p["elevation_m"] for p in recording.meta["points"]]  # type: ignore[attr-defined]  # JSON list
    assert from_raw == from_table


def test_the_recorded_values_are_plausible_metres(recording: Recording) -> None:
    values = list(recording.table.values())
    assert values and all(-1000.0 <= v <= 10000.0 for v in values)


def test_there_are_no_stray_files_in_the_recording_directory() -> None:
    top = sorted(p.name for p in RECORDED_DIR.iterdir())
    assert top == sorted(["raw", "record.py", *(f"{s}.json" for s in PARENTS)])


def test_parse_elevations_accepts_every_recorded_raw_body(recording: Recording) -> None:
    requests = recording.meta["requests"]
    assert isinstance(requests, list)
    for body, request in zip(recording.raw_bodies, requests, strict=True):
        expected = json.loads(body)["elevation"]
        parsed = parse_elevations(body, len(expected))
        assert parsed == tuple(expected), request["raw"]


def test_parse_elevations_equals_the_table_values_for_the_whole_route(
    recording: Recording,
) -> None:
    parsed: list[float] = []
    for body in recording.raw_bodies:
        batch = parse_elevations(body, len(json.loads(body)["elevation"]))
        assert batch is not None
        parsed.extend(batch)
    assert parsed == [p["elevation_m"] for p in recording.meta["points"]]  # type: ignore[attr-defined]  # JSON list
