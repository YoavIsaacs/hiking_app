"""summarise_upload with a fake ElevationLookup: orchestration, logging, no TestClient
(ADR 0005 sections 1 and 7)."""

import logging
import threading
from collections.abc import Sequence

import anyio
import pytest

from app.clients.elevation import LookupOutcome, LookupResult
from app.models.warnings import ELEVATION_UNAVAILABLE
from app.routes.errors import InvalidGpx
from app.routes.params import DEFAULT_PARAMS
from app.routes.summary import (
    lookup_point_count,
    summarise_gpx,
    with_looked_up_elevation,
)
from app.services.route_parse import summarise_upload
from tests.elevation_support import coord, synthetic_elevation
from tests.fixtures.loader import GPX_DIR
from tests.routes.gpx_builders import gpx_bytes, out_and_back, straight_line

pytestmark = pytest.mark.anyio

Coords = Sequence[tuple[float, float]]
NO_ELE = (GPX_DIR / "derived-tel-hadid-no-ele.gpx").read_bytes()
WITH_ELE = (GPX_DIR / "alltrails-tel-hadid-loop.gpx").read_bytes()


def values_for(coords: Coords) -> tuple[float, ...]:
    return tuple(synthetic_elevation(coord(a), coord(b)) for a, b in coords)


class FakeLookup:
    """Records what it was asked, where, and with which parse slots held."""

    def __init__(
        self,
        limiter: anyio.CapacityLimiter,
        *,
        outcome: LookupOutcome = "ok",
        status_code: int | None = None,
        calls: int = 4,
        batches: int = 4,
    ) -> None:
        self.limiter = limiter
        self.outcome = outcome
        self.status_code = status_code
        self.calls_reported = calls
        self.batches_reported = batches
        self.asked: list[Coords] = []
        self.threads: list[int] = []
        self.borrowed: list[int] = []

    async def lookup(self, coords: Coords) -> LookupResult:
        self.asked.append(list(coords))
        self.threads.append(threading.get_ident())
        self.borrowed.append(self.limiter.borrowed_tokens)
        ok = self.outcome == "ok"
        return LookupResult(
            elevations=values_for(coords) if ok else None,
            outcome=self.outcome,
            calls=self.calls_reported,
            batches=self.batches_reported,
            status_code=self.status_code,
        )


def elevation_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.elevation"]


@pytest.fixture
def limiter() -> anyio.CapacityLimiter:
    return anyio.CapacityLimiter(1)


@pytest.fixture(autouse=True)
def _capture(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.elevation")


# --- files with elevation never look anything up ------------------


async def test_a_file_with_elevation_makes_no_lookup_and_no_log_line(
    limiter: anyio.CapacityLimiter, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeLookup(limiter)
    summary = await summarise_upload(WITH_ELE, "a.gpx", limiter=limiter, elevation=fake)
    assert fake.asked == []
    assert summary == summarise_gpx(WITH_ELE, "a.gpx")
    assert summary.elevation_source == "file"
    assert elevation_records(caplog) == []


async def test_a_file_with_elevation_does_not_need_the_lifespan(
    limiter: anyio.CapacityLimiter,
) -> None:
    summary = await summarise_upload(WITH_ELE, "a.gpx", limiter=limiter, elevation=None)
    assert summary.elevation_source == "file"


# --- no lifespan: a loud wiring bug ------------------


async def test_a_no_elevation_file_without_a_lookup_is_a_runtime_error(
    limiter: anyio.CapacityLimiter, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(RuntimeError, match="lifespan"):
        await summarise_upload(NO_ELE, "a.gpx", limiter=limiter, elevation=None)
    assert elevation_records(caplog) == []


# --- parse errors pass straight through ------------------


async def test_a_route_parse_error_propagates_and_nothing_is_looked_up(
    limiter: anyio.CapacityLimiter,
) -> None:
    fake = FakeLookup(limiter)
    with pytest.raises(InvalidGpx):
        await summarise_upload(b"not gpx", "a.gpx", limiter=limiter, elevation=fake)
    assert fake.asked == []


# --- success ------------------


async def test_it_looks_up_exactly_the_stage_one_points_and_fills_them_in(
    limiter: anyio.CapacityLimiter,
) -> None:
    fake = FakeLookup(limiter)
    stage1 = summarise_gpx(NO_ELE, "a.gpx")
    result = await summarise_upload(NO_ELE, "a.gpx", limiter=limiter, elevation=fake)

    assert len(fake.asked) == 1
    assert list(fake.asked[0]) == [(p.lat, p.lon) for p in stage1.points]
    assert len(stage1.points) == lookup_point_count(stage1.distance_m, DEFAULT_PARAMS)
    assert result.elevation_source == "lookup" and result.has_elevation is True
    assert result.warnings == []
    assert result == with_looked_up_elevation(stage1, values_for(fake.asked[0]))


async def test_the_lookup_runs_on_the_event_loop_outside_the_parse_slot(
    limiter: anyio.CapacityLimiter,
) -> None:
    fake = FakeLookup(limiter)
    await summarise_upload(NO_ELE, "a.gpx", limiter=limiter, elevation=fake)
    assert fake.threads == [threading.get_ident()], "lookup must await on the loop"
    assert fake.borrowed == [0], "the parse slot must be free while Open-Meteo is slow"
    assert limiter.borrowed_tokens == 0


async def test_a_slow_lookup_does_not_block_another_parse(
    limiter: anyio.CapacityLimiter,
) -> None:
    entered, release = anyio.Event(), anyio.Event()

    class Slow(FakeLookup):
        async def lookup(self, coords: Coords) -> LookupResult:
            entered.set()
            await release.wait()
            return await super().lookup(coords)

    slow = Slow(limiter)

    async def first() -> None:
        await summarise_upload(NO_ELE, "a.gpx", limiter=limiter, elevation=slow)

    with anyio.fail_after(20):
        async with anyio.create_task_group() as group:
            group.start_soon(first)
            await entered.wait()
            other = await summarise_upload(
                WITH_ELE, "b.gpx", limiter=limiter, elevation=slow
            )
            assert other.elevation_source == "file"  # served while the lookup waits
            release.set()


# --- failure ------------------


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        ("timeout", None),
        ("transport_error", None),
        ("http_status", 503),
        ("http_status", 429),
        ("bad_response", None),
    ],
)
async def test_every_failed_outcome_returns_stage_one_plus_the_warning(
    limiter: anyio.CapacityLimiter, outcome: LookupOutcome, status: int | None
) -> None:
    fake = FakeLookup(limiter, outcome=outcome, status_code=status, calls=2, batches=4)
    stage1 = summarise_gpx(NO_ELE, "a.gpx")
    result = await summarise_upload(NO_ELE, "a.gpx", limiter=limiter, elevation=fake)
    assert result.warnings == [ELEVATION_UNAVAILABLE]
    assert result.model_copy(update={"warnings": []}) == stage1
    assert result.elevation_source == "none" and result.has_elevation is False
    assert result.gain_m is None and result.high_point is None
    assert all(p.elev_m is None for p in result.points)


async def test_an_unexpected_lookup_exception_is_not_swallowed(
    limiter: anyio.CapacityLimiter,
) -> None:
    class Broken(FakeLookup):
        async def lookup(self, coords: Coords) -> LookupResult:
            raise KeyError("a bug, not an outage")

    with pytest.raises(KeyError):
        await summarise_upload(
            NO_ELE, "a.gpx", limiter=limiter, elevation=Broken(limiter)
        )


# --- the log line ------------------


async def test_a_successful_lookup_logs_one_info_line_with_the_documented_fields(
    limiter: anyio.CapacityLimiter, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeLookup(limiter, calls=4, batches=4)
    await summarise_upload(NO_ELE, "a.gpx", limiter=limiter, elevation=fake)
    (record,) = elevation_records(caplog)
    assert record.getMessage() == "elevation_lookup"
    assert record.levelno == logging.INFO
    fields = record.__dict__
    stage1 = summarise_gpx(NO_ELE, "a.gpx")
    assert fields["points"] == len(stage1.points)
    assert fields["points"] == lookup_point_count(stage1.distance_m, DEFAULT_PARAMS)
    assert fields["batches"] == 4
    assert fields["calls"] == 4
    assert fields["outcome"] == "ok"
    assert fields["status_code"] is None
    assert isinstance(fields["duration_ms"], float) and fields["duration_ms"] >= 0


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        ("timeout", None),
        ("transport_error", None),
        ("http_status", 503),
        ("bad_response", None),
    ],
)
async def test_a_failed_lookup_logs_one_warning_line_with_the_outcome_and_status(
    limiter: anyio.CapacityLimiter,
    caplog: pytest.LogCaptureFixture,
    outcome: LookupOutcome,
    status: int | None,
) -> None:
    fake = FakeLookup(limiter, outcome=outcome, status_code=status, calls=2, batches=1)
    data = gpx_bytes([straight_line(60, step_m=135.0, ele=None)])
    await summarise_upload(data, "a.gpx", limiter=limiter, elevation=fake)
    (record,) = elevation_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.__dict__["outcome"] == outcome
    assert record.__dict__["status_code"] == status
    assert (record.__dict__["points"], record.__dict__["calls"]) == (60, 2)
    assert record.__dict__["batches"] == 1


async def test_one_line_per_attempted_lookup(
    limiter: anyio.CapacityLimiter, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeLookup(limiter)
    data = gpx_bytes([out_and_back()])  # has elevation: no lookup, no line
    await summarise_upload(data, "a.gpx", limiter=limiter, elevation=fake)
    for _ in range(3):
        await summarise_upload(NO_ELE, "a.gpx", limiter=limiter, elevation=fake)
    assert len(elevation_records(caplog)) == 3
    assert len(fake.asked) == 3
