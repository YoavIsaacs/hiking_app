"""RSS probe: repeated hostile uploads must not ratchet the API's memory.

ADR 0004 item 55.

QA's check for step 1.3a. It runs inside the production image (no pytest, no network
beyond localhost) and is what the ``api-image`` CI job runs:

    docker run --rm --memory=512m -v "$PWD/api/tests:/app/tests:ro" \
        --entrypoint python hike-api:ci -m tests.routes.rss_probe

What it does, in a fresh container each time:

1. starts uvicorn with the image's CMD settings (``HIKE_OPEN_METEO_BASE_URL`` points
   at a closed local port, so nothing goes live);
2. posts 60 sequential H2 U=256 10 MiB uploads over HTTP, sampling the server's
   ``VmRSS``/``VmHWM`` from ``/proc/<pid>/status`` after requests 1, 3, 5, 10 and 60;
3. runs the concurrent smoke (8 hostile uploads in flight, a few rounds) on the same,
   already-ratcheted server and records the peak RSS and every status code;
4. on a second fresh server, times H11(d) once over HTTP;
5. prints a table and exits 1 if a bar below fails.

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
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uvicorn

from tests.routes.h_rows import h2, h11
from tests.routes.http_helpers import (
    URL,
    multipart_content_type,
    multipart_head,
    multipart_tail,
)

MIB = 1024 * 1024

# --- The bars: docs/steps/1.3a.md, "Checkpoint" (1) to (3). Do not loosen. ---------
RSS_AFTER_10_MAX_MIB = 200.0  # checked after request 10 and again after request 60
CONCURRENT_PEAK_MAX_MIB = 400.0  # exclusive: the peak must be < this
H11D_MAX_S = 3.5  # exclusive: H11(d) must take < this
# "No 500 and no OOM": any status >= 500, a refused or reset connection, or a dead
# server process fails the probe.

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
    h11d_s: float | None = None
    h11d_status: int | None = None


def evaluate(report: Report) -> list[str]:
    """The failed bars, as messages. Empty means the probe passes. Pure."""
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
    bad = sorted({s for s in report.statuses if s >= 500})
    if bad:
        failed.append(f"server answered with status {bad}, bar is no 5xx")
    failed.extend(report.errors)
    if report.h11d_s is None:
        failed.append("no H11(d) time recorded")
    elif report.h11d_s >= H11D_MAX_S:
        failed.append(f"H11(d) took {report.h11d_s:.2f} s, bar is < {H11D_MAX_S} s")
    if report.h11d_status is not None and report.h11d_status >= 500:
        failed.append(f"H11(d) answered {report.h11d_status}")
    return failed


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


class Server:
    """uvicorn as the image's CMD starts it, on ``PORT``, as a child process."""

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
            stdout=subprocess.DEVNULL,  # the JSON access log; statuses are printed
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

    def rss(self) -> tuple[float, float]:
        return proc_status_mib(self.proc.pid)


def sequential(server: Server, body: bytes, report: Report) -> None:
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


def concurrent(server: Server, body: bytes, report: Report) -> list[list[int]]:
    peak = 0.0
    stop = threading.Event()
    can_reset = reset_hwm(server.proc.pid)

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


def run_probe() -> int:
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
    with Server():
        data = multipart_body(h11("d"))
        try:
            status, secs = post(data)
            report.h11d_status, report.h11d_s = status, secs
            print(f"H11(d) over HTTP: status {status} in {secs:.2f} s", flush=True)
        except OSError as error:
            report.errors.append(f"H11(d) failed: {error!r}")

    print("\n  after upload | RSS MiB | peak RSS (VmHWM) MiB")
    for s in report.samples:
        print(f"  {s.n:>12} | {s.rss_mib:7.1f} | {s.hwm_mib:7.1f}")
    peak = report.concurrent_peak_mib
    print(f"  concurrent peak RSS: {'n/a' if peak is None else f'{peak:.1f}'} MiB")
    codes = sorted(set(report.statuses))
    print(f"  status codes seen: {codes}")
    print(f"  wall time: {time.monotonic() - started:.0f} s")
    failed = evaluate(report)
    for message in failed:
        print(f"FAIL: {message}")
    print("RESULT: " + ("FAIL" if failed else "PASS"))
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
        "--diagnose-child", choices=DIAGNOSE_MODES, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    if args.diagnose_child:
        return diagnose_child(args.diagnose_child)
    if args.diagnose:
        return run_diagnose()
    return run_probe()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
