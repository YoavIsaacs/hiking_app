"""RSS probe: repeated hostile uploads must not ratchet the API's memory.

ADR 0004 item 55.

QA's check for step 1.3a. It runs inside the production image (no pytest, no network
beyond localhost) and is what the ``api-image`` CI job runs:

    docker run --rm --memory=512m --memory-swap=512m \
        -v "$PWD/api/tests:/app/tests:ro" \
        --entrypoint python hike-api:ci -m tests.routes.rss_probe

What it does, in a fresh container each time:

1. starts uvicorn with the image's CMD settings (``HIKE_OPEN_METEO_BASE_URL`` points
   at a closed local port, so nothing goes live);
2. posts 60 sequential H2 U=256 10 MiB uploads over HTTP, sampling the server's
   ``VmRSS``/``VmHWM`` from ``/proc/<pid>/status`` after requests 1, 3, 5, 10 and 60;
3. runs the concurrent smoke (8 hostile uploads in flight, a few rounds) on the same,
   already-ratcheted server and records the peak RSS and every status code;
4. on a second fresh server, posts H11(d) 3 times over HTTP and reports the median,
   with the server's own ``elevation_lookup`` ``duration_ms`` (from its log) beside it,
   so parse time and the failed-lookup time are printed separately;
5. prints a table and exits 1 if a memory bar or a status bar fails (every hostile
   upload must be 422, every H11(d) 200). The H11(d) time bar is a ``::warning::``
   annotation, not a failure, because it flaked on shared CI hosts; ``--enforce-time``
   makes it fail (use it for local checkpoint runs).

``--shape NAME [NAME ...]`` (or ``all``) runs only the sequential phase, over HTTP,
for the other request shapes in ``reject_shapes.py`` (``too_many_points``, 413s,
validation errors, accepted uploads whose elevation lookup fails): one fresh server per
shape, the same RSS bar, and a failure if the status is not the one the shape gets.

``--diagnose`` is the investigation mode (ADR 0004 follow-up). It serves the app *inside
this process* (``create_app`` under uvicorn's programmatic API, in a thread) so that
``tracemalloc``, ``gc`` and ``malloc_trim`` can be called in the server's own process.
Its numbers are in-process numbers, not the HTTP-probe's separate-process numbers: RSS
there is this process's, so it includes the client's ~25 MiB of upload buffers.
"""

import argparse
import contextlib
import ctypes
import gc
import http.client
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import IO, TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uvicorn

from tests.routes.h_rows import h2, h11
from tests.routes.http_helpers import (
    URL,
    multipart_content_type,
    multipart_head,
    multipart_tail,
)
from tests.routes.reject_shapes import Shape, all_shapes

MIB = 1024 * 1024

# --- The bars: docs/steps/1.3a.md, "Checkpoint" (1) to (3). Do not loosen. ---------
RSS_AFTER_10_MAX_MIB = 200.0  # checked after request 10 and again after request 60
CONCURRENT_PEAK_MAX_MIB = 400.0  # exclusive: the peak must be < this
# Exclusive: the median of H11D_POSTS H11(d) posts must be < this. A warning by default,
# a failure with --enforce-time (docs/steps/1.3a.md, "Review round 1").
H11D_MAX_S = 3.5
H11D_POSTS = 3
# "No 500 and no OOM", and every status is the expected one: a hostile upload that is
# not 422, an H11(d) that is not 200, a refused or reset connection, or a dead server
# process fails the probe.
HOSTILE_STATUS = 422
H11D_STATUS = 200

SAMPLE_AT = (1, 3, 5, 10, 60)
SEQUENTIAL = max(SAMPLE_AT)
CONCURRENCY = 8
ROUNDS = 3
PORT = 8791  # not 8765, which the other harnesses use
HOST = "127.0.0.1"
CLOSED_PORT_URL = "http://127.0.0.1:9"  # nothing listens: no live Open-Meteo calls
REQUEST_TIMEOUT_S = 180.0


@dataclass
class Sample:
    n: int
    rss_mib: float
    hwm_mib: float


@dataclass
class Report:
    samples: list[Sample] = field(default_factory=list)
    concurrent_peak_mib: float | None = None
    statuses: list[int] = field(default_factory=list)  # sequential and concurrent
    errors: list[str] = field(default_factory=list)  # dead process, connection errors
    h11d_s: float | None = None  # the median over the H11(d) posts
    h11d_statuses: list[int] = field(default_factory=list)
    h11d_lookup_ms: list[float] = field(default_factory=list)  # server-side, from logs


def time_warning(report: Report) -> str | None:
    """The H11(d) time bar as a message when it is missed, else None. Pure."""
    if report.h11d_s is not None and report.h11d_s >= H11D_MAX_S:
        return (
            f"H11(d) median took {report.h11d_s:.2f} s, bar is < {H11D_MAX_S} s"
            f"{lookup_note(report)}"
        )
    return None


def lookup_note(report: Report) -> str:
    if not report.h11d_lookup_ms:
        return ""
    ms = statistics.median(report.h11d_lookup_ms)
    return f" (of which elevation_lookup {ms / 1000:.2f} s)"


def evaluate(report: Report, enforce_time: bool = False) -> list[str]:
    """The failed bars, as messages. Empty means the probe passes. Pure.

    The H11(d) time bar only fails the probe with ``enforce_time``; otherwise it is
    ``time_warning``.
    """
    failed: list[str] = []
    by_n = {s.n: s for s in report.samples}
    for n in (10, SEQUENTIAL):
        sample = by_n.get(n)
        if sample is None:
            failed.append(f"no RSS sample after request {n}")
        elif sample.rss_mib > RSS_AFTER_10_MAX_MIB:
            failed.append(
                f"RSS after {n} uploads is {sample.rss_mib:.1f} MiB,"
                f" bar is <= {RSS_AFTER_10_MAX_MIB:.0f} MiB"
            )
    peak = report.concurrent_peak_mib
    if peak is None:
        failed.append("no concurrent peak recorded")
    elif peak >= CONCURRENT_PEAK_MAX_MIB:
        failed.append(
            f"concurrent peak RSS is {peak:.1f} MiB,"
            f" bar is < {CONCURRENT_PEAK_MAX_MIB:.0f} MiB"
        )
    bad = sorted({s for s in report.statuses if s != HOSTILE_STATUS})
    if bad:
        failed.append(
            f"hostile uploads answered with status {bad}, bar is {HOSTILE_STATUS} only"
        )
    failed.extend(report.errors)
    if report.h11d_s is None:
        failed.append("no H11(d) time recorded")
    elif enforce_time:
        message = time_warning(report)
        if message:
            failed.append(message)
    bad_h11d = sorted({s for s in report.h11d_statuses if s != H11D_STATUS})
    if bad_h11d:
        failed.append(f"H11(d) answered {bad_h11d}, bar is {H11D_STATUS} only")
    return failed


def lookup_durations_ms(log_text: str) -> list[float]:
    """``duration_ms`` of every ``elevation_lookup`` line in the server's JSON log."""
    found: list[float] = []
    for line in log_text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(record, dict)
            and record.get("message") == "elevation_lookup"
            and isinstance(record.get("duration_ms"), int | float)
        ):
            found.append(float(record["duration_ms"]))
    return found


# --- /proc ----------------------------------------------------------------------------


def proc_status_mib(pid: int | str) -> tuple[float, float]:
    """(VmRSS, VmHWM) of a process in MiB, from /proc/<pid>/status."""
    return parse_status(_read(f"/proc/{pid}/status"))


def _read(path: str) -> str:
    with open(path) as handle:
        return handle.read()


def parse_status(text: str) -> tuple[float, float]:
    found: dict[str, float] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key in ("VmRSS", "VmHWM"):
            found[key] = int(rest.split()[0]) / 1024  # kB -> MiB
    return found["VmRSS"], found["VmHWM"]


def reset_hwm(pid: int | str) -> bool:
    """Reset VmHWM to the current RSS (Linux >= 4.0); False if not permitted."""
    try:
        with open(f"/proc/{pid}/clear_refs", "w") as handle:
            handle.write("5")
    except OSError:
        return False
    return True


# --- HTTP -----------------------------------------------------------------------------


def multipart_body(gpx: bytes) -> bytes:
    return multipart_head() + gpx + multipart_tail()


def post(body: bytes) -> tuple[int, float]:
    """POST one upload; (status, seconds). http.client keeps client memory flat."""
    conn = http.client.HTTPConnection(HOST, PORT, timeout=REQUEST_TIMEOUT_S)
    started = time.perf_counter()
    try:
        conn.request(
            "POST",
            URL,
            body=body,
            headers={
                "Content-Type": multipart_content_type(),
                "Content-Length": str(len(body)),
            },
        )
        response = conn.getresponse()
        response.read()
        return response.status, time.perf_counter() - started
    finally:
        conn.close()


def post_shape(shape: Shape) -> int | None:
    """POST a shape; its status, or None if the server cut the connection after
    answering early (a 413 sent before the body was read)."""
    conn = http.client.HTTPConnection(HOST, PORT, timeout=REQUEST_TIMEOUT_S)
    headers = {"Content-Type": shape.headers_content_type}
    try:
        if shape.chunked:
            conn.request(
                "POST",
                URL,
                body=(shape.body[i : i + MIB] for i in range(0, len(shape.body), MIB)),
                headers=headers,
                encode_chunked=True,
            )
        else:
            headers["Content-Length"] = str(len(shape.body))
            conn.request("POST", URL, body=shape.body, headers=headers)
        response = conn.getresponse()
        response.read()
        return response.status
    except (BrokenPipeError, ConnectionResetError):
        return None
    finally:
        conn.close()


def wait_ready(alive: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if not alive():
            raise RuntimeError("server exited before it was ready")
        try:
            conn = http.client.HTTPConnection(HOST, PORT, timeout=2)
            conn.request("GET", "/health")
            if conn.getresponse().status == 200:
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("server not ready after 60 s")


# --- the server as a separate process (the probe proper) -----------------------------


class ServerLike(Protocol):
    """What the sequential and concurrent phases need from a server (tests stub it)."""

    @property
    def alive(self) -> bool: ...

    @property
    def pid(self) -> int: ...

    def rss(self) -> tuple[float, float]: ...


class Server:
    """uvicorn as the image's CMD starts it, on ``PORT``, as a child process."""

    def __init__(self, log: IO[str] | None = None) -> None:
        self.log = log  # the server's stderr (its JSON log); None inherits ours

    def __enter__(self) -> "Server":
        env = os.environ | {
            "HIKE_OPEN_METEO_BASE_URL": CLOSED_PORT_URL,
            "PORT": str(PORT),
        }
        # The image CMD: sh -c "exec uvicorn app.main:create_app --factory
        # --host 0.0.0.0 --port ${PORT:-8080}".
        # Bound to loopback here: only this process talks to it.
        self.proc = subprocess.Popen(
            [
                "sh",
                "-c",
                "exec uvicorn app.main:create_app --factory --host 127.0.0.1"
                " --port ${PORT:-8080}",
            ],
            env=env,
            cwd=os.getcwd(),
            stdout=subprocess.DEVNULL,  # statuses are printed by the probe
            stderr=self.log,
        )
        wait_ready(lambda: self.proc.poll() is None)
        return self

    def __exit__(self, *exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    @property
    def pid(self) -> int:
        return self.proc.pid

    def rss(self) -> tuple[float, float]:
        return proc_status_mib(self.proc.pid)


def sequential(server: ServerLike, body: bytes, report: Report) -> None:
    for n in range(1, SEQUENTIAL + 1):
        try:
            status, secs = post(body)
        except OSError as error:
            report.errors.append(f"upload {n} failed: {error!r}")
            return
        report.statuses.append(status)
        if not server.alive:
            report.errors.append(f"server process died during upload {n} (OOM?)")
            return
        if n in SAMPLE_AT:
            rss, hwm = server.rss()
            report.samples.append(Sample(n, rss, hwm))
            print(
                f"  seq {n:>2}: status {status} {secs:5.2f}s"
                f" RSS {rss:6.1f} HWM {hwm:6.1f} MiB",
                flush=True,
            )


def concurrent(server: ServerLike, body: bytes, report: Report) -> list[list[int]]:
    peak = 0.0
    stop = threading.Event()
    can_reset = reset_hwm(server.pid)

    def watch() -> None:
        nonlocal peak
        while not stop.is_set():
            with contextlib.suppress(OSError, KeyError):
                peak = max(peak, server.rss()[0])
            time.sleep(0.05)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    rounds: list[list[int]] = []
    try:
        for r in range(ROUNDS):
            with ThreadPoolExecutor(CONCURRENCY) as pool:
                futures = [pool.submit(post, body) for _ in range(CONCURRENCY)]
                statuses: list[int] = []
                for future in futures:
                    try:
                        statuses.append(future.result()[0])
                    except OSError as error:
                        report.errors.append(f"concurrent round {r + 1}: {error!r}")
            rounds.append(statuses)
            report.statuses.extend(statuses)
            if not server.alive:
                report.errors.append(
                    f"server process died in concurrent round {r + 1} (OOM?)"
                )
                break
    finally:
        stop.set()
        watcher.join()
    with contextlib.suppress(OSError, KeyError):
        rss, hwm = server.rss()
        peak = max(peak, rss, hwm if can_reset else 0.0)
    report.concurrent_peak_mib = peak
    return rounds


def run_h11d(report: Report) -> None:
    """Post H11(d) H11D_POSTS times on a fresh server; median, lookup from its log."""
    data = multipart_body(h11("d"))
    times: list[float] = []
    with tempfile.TemporaryFile("w+") as log:
        with Server(log):
            for i in range(1, H11D_POSTS + 1):
                try:
                    status, secs = post(data)
                except OSError as error:
                    report.errors.append(f"H11(d) post {i} failed: {error!r}")
                    break
                report.h11d_statuses.append(status)
                times.append(secs)
                print(f"H11(d) over HTTP #{i}: status {status} in {secs:.2f} s")
        log.seek(0)
        report.h11d_lookup_ms = lookup_durations_ms(log.read())
    if times:
        report.h11d_s = statistics.median(times)
        lookups = ", ".join(f"{ms / 1000:.2f}" for ms in report.h11d_lookup_ms)
        rest = report.h11d_s - _median_s(report.h11d_lookup_ms)
        print(
            f"H11(d) median {report.h11d_s:.2f} s; server-side elevation_lookup"
            f" [{lookups or 'not captured'}] s; parse and the rest ~ {rest:.2f} s",
            flush=True,
        )


def _median_s(ms: list[float]) -> float:
    return statistics.median(ms) / 1000 if ms else 0.0


def run_probe(enforce_time: bool = False) -> int:
    started = time.monotonic()
    report = Report()
    body = multipart_body(h2(256))
    print(f"H2 U=256 upload: {len(body) / MIB:.2f} MiB; port {PORT}", flush=True)
    with Server() as server:
        print(f"idle: RSS {server.rss()[0]:.1f} MiB", flush=True)
        print(f"sequential x{SEQUENTIAL}:", flush=True)
        sequential(server, body, report)
        rounds = []
        if not report.errors:
            print(f"concurrent C={CONCURRENCY} x{ROUNDS} rounds:", flush=True)
            rounds = concurrent(server, body, report)
            for i, statuses in enumerate(rounds, 1):
                print(f"  round {i}: {sorted(statuses)}", flush=True)
    del body
    run_h11d(report)

    print("\n  after upload | RSS MiB | peak RSS (VmHWM) MiB")
    for s in report.samples:
        print(f"  {s.n:>12} | {s.rss_mib:7.1f} | {s.hwm_mib:7.1f}")
    peak = report.concurrent_peak_mib
    print(f"  concurrent peak RSS: {'n/a' if peak is None else f'{peak:.1f}'} MiB")
    codes = sorted(set(report.statuses))
    print(f"  status codes seen: {codes}")
    print(f"  wall time: {time.monotonic() - started:.0f} s")
    failed = evaluate(report, enforce_time)
    warning = None if enforce_time else time_warning(report)
    if warning:
        print(f"::warning::{warning}")
    for message in failed:
        print(f"FAIL: {message}")
    print("RESULT: " + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


# --- --shape: the sequential phase for the other reject shapes ---


def run_shapes(names: Sequence[str]) -> int:
    """For each named shape (or ``all``): a fresh server, SEQUENTIAL posts, RSS sampled.

    Fails when a shape's status is not the one it is meant to produce, the server
    dies, or RSS after request 10 or 60 passes the bar.
    """
    shapes = all_shapes()
    chosen = list(shapes) if "all" in names else list(names)
    unknown = [n for n in chosen if n not in shapes]
    if unknown:
        print(f"unknown shape(s) {unknown}; known: {sorted(shapes)}")
        return 2
    failed: list[str] = []
    for name in chosen:
        shape = shapes[name]
        problems: list[str] = []
        with Server() as server:
            print(f"{name}: {len(shape.body) / MIB:.2f} MiB, expect {shape.status}")
            for n in range(1, SEQUENTIAL + 1):
                try:
                    status = post_shape(shape)
                except OSError as error:
                    problems.append(f"upload {n} failed: {error!r}")
                    break
                # status None is a 413 the server sent before it read the body
                early_413 = status is None and shape.status == 413
                if status != shape.status and not early_413:
                    problems.append(
                        f"upload {n}: status {status}, expected {shape.status}"
                    )
                    break
                if not server.alive:
                    problems.append(f"server process died during upload {n} (OOM?)")
                    break
                if n in SAMPLE_AT:
                    rss, hwm = server.rss()
                    print(
                        f"  seq {n:>2}: status {status} RSS {rss:6.1f} HWM {hwm:6.1f}"
                    )
                    if n in (10, SEQUENTIAL) and rss > RSS_AFTER_10_MAX_MIB:
                        problems.append(f"RSS after {n} is {rss:.1f} MiB")
        for message in problems:
            print(f"  FAIL: {message}")
        if problems:
            failed.append(name)
    print("RESULT: " + (f"FAIL {failed}" if failed else "PASS"))
    return 1 if failed else 0


# --- --diagnose: the app in this process, so we can look inside it -------------------

DIAGNOSE_MODES = ("plain", "observe", "intervene", "gc-each", "trim-each")


def malloc_trim() -> int:
    return int(ctypes.CDLL("libc.so.6").malloc_trim(0))


def self_rss() -> float:
    return proc_status_mib("self")[0]


def debug_malloc_stats() -> dict[str, int]:
    """A few pymalloc totals from sys._debugmallocstats() (it writes to fd 2)."""
    import re

    with tempfile.TemporaryFile("w+") as sink:
        saved = os.dup(2)
        try:
            os.dup2(sink.fileno(), 2)
            sys._debugmallocstats()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        sink.seek(0)
        text = sink.read()
    keys = {
        "arenas_allocated_current": r"# arenas allocated current\s*=\s*(\d+)",
        "arenas_allocated_total": r"# arenas allocated total\s*=\s*(\d+)",
        "arenas_reclaimed": r"# arenas reclaimed\s*=\s*(\d+)",
        "bytes_in_allocated_blocks": r"([\d,]+) bytes in allocated blocks",
        "bytes_in_available_blocks": r"([\d,]+) bytes in available blocks",
    }
    out: dict[str, int] = {}
    for key, pattern in keys.items():
        match = re.search(pattern, text)
        if match:
            out[key] = int(match.group(1).replace(",", ""))
    return out


def serve_in_process() -> "tuple[uvicorn.Server, threading.Thread]":
    import uvicorn

    from app.config import Settings
    from app.main import create_app

    settings = Settings(open_meteo_base_url=CLOSED_PORT_URL, log_level="ERROR")
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host=HOST, port=PORT, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_ready(thread.is_alive)
    return server, thread


def diagnose_child(mode: str) -> int:
    import tracemalloc

    if mode == "observe":
        tracemalloc.start(1)
    body = multipart_body(h2(256))
    server, thread = serve_in_process()
    print(f"[{mode}] in-process server; idle RSS {self_rss():.1f} MiB", flush=True)
    rows: list[dict[str, object]] = []
    for n in range(1, SEQUENTIAL + 1):
        status, _ = post(body)
        if status >= 500:
            print(f"[{mode}] upload {n}: status {status}", flush=True)
        if mode == "gc-each":
            gc.collect()
        elif mode == "trim-each":
            malloc_trim()
        time.sleep(0.2)
        if n not in SAMPLE_AT:
            continue
        row: dict[str, object] = {"n": n, "status": status, "rss": round(self_rss(), 1)}
        if mode == "observe":
            current, peak = tracemalloc.get_traced_memory()
            row |= {
                "tracemalloc_live_mib": round(current / MIB, 1),
                "tracemalloc_peak_mib": round(peak / MIB, 1),
                "gc_count": gc.get_count(),
                "gc_garbage": len(gc.garbage),
            }
        if mode == "intervene":
            row["gc_count_before"] = gc.get_count()
            row["gc_collected"] = gc.collect()
            row["gc_garbage"] = len(gc.garbage)
            row["rss_after_gc"] = round(self_rss(), 1)
            malloc_trim()
            row["rss_after_gc_and_trim"] = round(self_rss(), 1)
            if n == 10:
                row["pymalloc"] = debug_malloc_stats()
        rows.append(row)
        print(f"[{mode}] " + json.dumps(row), flush=True)
    server.should_exit = True
    thread.join(timeout=20)
    return 0


def run_diagnose() -> int:
    """One fresh child process per mode, so interventions don't disturb each other."""
    print("DIAGNOSE: app served IN-PROCESS (create_app under uvicorn in a thread);")
    print("RSS is this process's, so it includes the client's upload buffers.\n")
    code = 0
    for mode in DIAGNOSE_MODES:
        result = subprocess.run(
            [sys.executable, "-m", "tests.routes.rss_probe", "--diagnose-child", mode],
            check=False,
        )
        code = code or result.returncode
    return code


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diagnose", action="store_true", help="in-process investigation"
    )
    parser.add_argument(
        "--shape",
        nargs="+",
        metavar="NAME",
        help="sequential phase for these reject shapes (or 'all'), then exit",
    )
    parser.add_argument(
        "--enforce-time",
        action="store_true",
        help=f"fail (not warn) when the median H11(d) time is >= {H11D_MAX_S} s",
    )
    parser.add_argument(
        "--diagnose-child", choices=DIAGNOSE_MODES, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    if args.shape:
        return run_shapes(args.shape)
    if args.diagnose_child:
        return diagnose_child(args.diagnose_child)
    if args.diagnose:
        return run_diagnose()
    return run_probe(args.enforce_time)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
