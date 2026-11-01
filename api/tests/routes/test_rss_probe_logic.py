"""The RSS probe's pass/fail logic on canned numbers (the bars are tested)."""

import pytest

from tests.routes import rss_probe as probe
from tests.routes.rss_probe import Report, Sample, evaluate, parse_status


def good() -> Report:
    return Report(
        samples=[Sample(n, 120.0 + n, 130.0 + n) for n in probe.SAMPLE_AT],
        concurrent_peak_mib=300.0,
        statuses=[422] * 60 + [422] * 24,
        h11d_s=2.9,
        h11d_status=200,
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


@pytest.mark.parametrize(("status", "ok"), [(499, True), (500, False), (502, False)])
def test_any_5xx_fails(status: int, ok: bool) -> None:
    report = good()
    report.statuses.append(status)
    assert (evaluate(report) == []) is ok


def test_a_dead_server_or_refused_connection_fails() -> None:
    report = good()
    report.errors.append("server process died during upload 7 (OOM?)")
    assert evaluate(report) == ["server process died during upload 7 (OOM?)"]


@pytest.mark.parametrize(("secs", "ok"), [(3.49, True), (3.5, False), (None, False)])
def test_h11d_bar_is_exclusive_at_3_5_s(secs: float | None, ok: bool) -> None:
    report = good()
    report.h11d_s = secs
    assert (evaluate(report) == []) is ok


def test_parse_status_reads_vmrss_and_vmhwm_in_mib() -> None:
    text = "Name:\tpython\nVmHWM:\t  409600 kB\nVmRSS:\t  204800 kB\nThreads:\t3\n"
    assert parse_status(text) == (200.0, 400.0)
