"""The RSS probe's pass/fail logic on canned numbers (the bars are tested)."""

from collections.abc import Callable
from typing import IO

import pytest

from tests.routes import rss_probe as probe
from tests.routes.rss_probe import Report, Sample, evaluate, parse_status


def good() -> Report:
    return Report(
        samples=[Sample(n, 120.0 + n, 130.0 + n) for n in probe.SAMPLE_AT],
        concurrent_peak_mib=300.0,
        statuses=[422] * 60 + [422] * 24,
        h11d_s=2.9,
        h11d_statuses=[200, 200, 200],
    )


def test_passes_when_every_bar_holds() -> None:
    assert evaluate(good()) == []


def test_bars_match_the_step_brief() -> None:
    assert probe.RSS_AFTER_10_MAX_MIB == 200
    assert probe.CONCURRENT_PEAK_MAX_MIB == 400
    assert probe.H11D_MAX_S == 3.5
    assert probe.SAMPLE_AT == (1, 3, 5, 10, 60)
    assert probe.CONCURRENCY == 8


def test_the_ratchet_from_adr_item_55_fails() -> None:
    report = good()
    report.samples = [
        Sample(1, 118.7, 120.0),
        Sample(3, 194.9, 200.0),
        Sample(5, 320.0, 330.0),
        Sample(10, 383.0, 390.0),
        Sample(60, 398.0, 400.0),
    ]
    failed = evaluate(report)
    assert len(failed) == 2
    assert "after 10 uploads" in failed[0]
    assert "after 60 uploads" in failed[1]


@pytest.mark.parametrize(("rss", "ok"), [(200.0, True), (200.01, False)])
def test_rss_bar_is_inclusive_at_200(rss: float, ok: bool) -> None:
    report = good()
    report.samples[-1] = Sample(60, rss, rss)
    assert (evaluate(report) == []) is ok


def test_rss_at_request_5_is_not_judged() -> None:
    report = good()
    report.samples[2] = Sample(5, 350.0, 350.0)
    assert evaluate(report) == []


def test_a_missing_sample_fails() -> None:
    report = good()
    report.samples = report.samples[:3]
    assert len(evaluate(report)) == 2


@pytest.mark.parametrize(("peak", "ok"), [(399.9, True), (400.0, False), (None, False)])
def test_concurrent_peak_bar_is_exclusive_at_400(peak: float | None, ok: bool) -> None:
    report = good()
    report.concurrent_peak_mib = peak
    assert (evaluate(report) == []) is ok


@pytest.mark.parametrize(
    ("status", "ok"),
    [(422, True), (200, False), (413, False), (499, False), (500, False), (502, False)],
)
def test_every_hostile_upload_must_be_422(status: int, ok: bool) -> None:
    report = good()
    report.statuses.append(status)  # sequential and concurrent share the list
    assert (evaluate(report) == []) is ok


@pytest.mark.parametrize(
    ("statuses", "ok"),
    [([200, 200, 200], True), ([200, 422, 200], False), ([200, 500, 200], False)],
)
def test_every_h11d_post_must_be_200(statuses: list[int], ok: bool) -> None:
    report = good()
    report.h11d_statuses = statuses
    assert (evaluate(report) == []) is ok


def test_a_dead_server_or_refused_connection_fails() -> None:
    report = good()
    report.errors.append("server process died during upload 7 (OOM?)")
    assert evaluate(report) == ["server process died during upload 7 (OOM?)"]


@pytest.mark.parametrize(("secs", "warns"), [(3.49, False), (3.5, True), (4.4, True)])
def test_h11d_time_is_a_warning_not_a_failure_by_default(
    secs: float, warns: bool
) -> None:
    report = good()
    report.h11d_s = secs
    assert evaluate(report) == []
    assert (probe.time_warning(report) is not None) is warns


@pytest.mark.parametrize(("secs", "ok"), [(3.49, True), (3.5, False)])
def test_h11d_bar_is_exclusive_at_3_5_s_with_enforce_time(
    secs: float, ok: bool
) -> None:
    report = good()
    report.h11d_s = secs
    failed = evaluate(report, enforce_time=True)
    assert (failed == []) is ok
    assert ok or "H11(d) median took" in failed[0]


@pytest.mark.parametrize("enforce", [False, True])
def test_a_missing_h11d_time_fails_in_both_modes(enforce: bool) -> None:
    report = good()
    report.h11d_s = None
    assert evaluate(report, enforce_time=enforce) == ["no H11(d) time recorded"]


def test_the_time_warning_separates_the_lookup_time() -> None:
    report = good()
    report.h11d_s = 4.0
    report.h11d_lookup_ms = [1200.0, 1250.0, 1300.0]
    warning = probe.time_warning(report)
    assert warning is not None
    assert "elevation_lookup 1.25 s" in warning


def test_lookup_durations_are_read_from_the_servers_json_log() -> None:
    log = "\n".join(
        [
            "not json",
            '{"message": "elevation_lookup", "duration_ms": 1250.5}',
            '{"message": "request", "duration_ms": 9000}',
            '{"message": "elevation_lookup", "duration_ms": "slow"}',
            '["elevation_lookup"]',
            '{"message": "elevation_lookup", "duration_ms": 3}',
        ]
    )
    assert probe.lookup_durations_ms(log) == [1250.5, 3.0]


def test_h11d_is_posted_three_times_and_the_median_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([4.4, 3.1, 3.2])

    def fake_post(body: bytes) -> tuple[int, float]:
        return 200, next(times)

    class FakeServer:
        def __init__(self, log: IO[str] | None = None) -> None:
            self.log = log

        def __enter__(self) -> "FakeServer":
            assert self.log is not None
            self.log.write('{"message": "elevation_lookup", "duration_ms": 1200}\n')
            self.log.flush()
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(probe, "post", fake_post)
    monkeypatch.setattr(probe, "Server", FakeServer)
    report = Report()
    probe.run_h11d(report)
    assert report.h11d_s == 3.2  # the median, not the 4.4 outlier or the mean
    assert report.h11d_statuses == [200, 200, 200]
    assert report.h11d_lookup_ms == [1200.0]
    assert probe.H11D_POSTS == 3


def test_parse_status_reads_vmrss_and_vmhwm_in_mib() -> None:
    text = "Name:\tpython\nVmHWM:\t  409600 kB\nVmRSS:\t  204800 kB\nThreads:\t3\n"
    assert parse_status(text) == (200.0, 400.0)


# --- the probe's own loops, with a stub server: a dead server must fail the run ---


class StubServer:
    """Stands in for ``Server``: alive until ``die_after`` requests have been made."""

    def __init__(self, die_after: int | None = None) -> None:
        self.die_after = die_after
        self.posts = 0

    pid = 1

    @property
    def alive(self) -> bool:
        return self.die_after is None or self.posts < self.die_after

    def rss(self) -> tuple[float, float]:
        return 100.0, 100.0


def counting_post(
    server: StubServer, status: int = 422
) -> Callable[[bytes], tuple[int, float]]:
    def post(body: bytes) -> tuple[int, float]:
        server.posts += 1
        return status, 0.1

    return post


def test_the_sequential_phase_reports_a_server_that_died_and_fails_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = StubServer(die_after=7)
    monkeypatch.setattr(probe, "post", counting_post(server))
    report = Report()
    probe.sequential(server, b"x", report)
    assert any("died during upload 7" in e for e in report.errors)
    assert server.posts == 7  # it stops at the death, it does not keep posting
    assert evaluate(report) != []


def test_the_sequential_phase_reports_a_refused_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(body: bytes) -> tuple[int, float]:
        raise ConnectionRefusedError("down")

    monkeypatch.setattr(probe, "post", refuse)
    report = Report()
    probe.sequential(StubServer(), b"x", report)
    assert any("upload 1 failed" in e for e in report.errors)
    assert evaluate(report) != []


def test_the_concurrent_phase_reports_a_server_that_died(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = StubServer(die_after=8)
    monkeypatch.setattr(probe, "post", counting_post(server))
    monkeypatch.setattr(probe, "reset_hwm", lambda pid: False)
    report = Report()
    probe.concurrent(server, b"x", report)
    assert any("died in concurrent round 1" in e for e in report.errors)
    assert evaluate(report) != []


def test_a_shape_with_the_wrong_status_fails_the_shape_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Fake:
        alive = True
        proc = type("Proc", (), {"pid": 1})()

        def __enter__(self) -> "Fake":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def rss(self) -> tuple[float, float]:
            return 100.0, 100.0

    monkeypatch.setattr(probe, "Server", Fake)
    monkeypatch.setattr(probe, "post_shape", lambda shape: 500)
    assert probe.run_shapes(["empty_file"]) == 1
    monkeypatch.setattr(probe, "post_shape", lambda shape: 422)
    assert probe.run_shapes(["empty_file"]) == 0
    assert probe.run_shapes(["no-such-shape"]) == 2


def test_a_shape_run_fails_when_rss_passes_the_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Fat:
        alive = True
        proc = type("Proc", (), {"pid": 1})()

        def __enter__(self) -> "Fat":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def rss(self) -> tuple[float, float]:
            return 250.0, 250.0

    monkeypatch.setattr(probe, "Server", Fat)
    monkeypatch.setattr(probe, "post_shape", lambda shape: 422)
    assert probe.run_shapes(["empty_file"]) == 1
