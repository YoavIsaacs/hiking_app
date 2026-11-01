"""Worst-case hostile XML generators and a child-process runner (ADR 0004 3.13).

Names are generated shortest-first (every legal 1-character name, then every
2-character name, ...), because that packs the most distinct names into a byte budget.
The first character is from ``[A-Za-z_]``, the later ones from ``[A-Za-z0-9_.-]``;
names starting with ``xml`` in any case are skipped (reserved; ``xmlns`` would become a
declaration).
"""

import itertools
import json
import string
import subprocess
import sys
import textwrap
from collections.abc import Iterator, Sequence
from functools import cache
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2]
KIB = 1024
MIB = 1024 * 1024
TWO_POINTS = (
    b'<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>'
)

_FIRST = string.ascii_letters + "_"
_REST = _FIRST + string.digits + ".-"


def shortest_first_names() -> Iterator[str]:
    length = 1
    while True:
        pools = [_FIRST, *([_REST] * (length - 1))]
        for combo in itertools.product(*pools):
            name = "".join(combo)
            if not name.lower().startswith("xml"):
                yield name
        length += 1


def burst(template: str, size: int) -> str:
    """``template % name`` for shortest-first names, as many as fit in ``size``."""
    out: list[str] = []
    total = 0
    for name in shortest_first_names():
        piece = template % name
        total += len(piece)
        if total > size:
            break
        out.append(piece)
    return "".join(out)


@cache
def prefixed_attribute_burst(size: int, uri_len: int) -> bytes:
    """The round-3 shape: a prefix bound to a ``uri_len``-byte URI, then distinct
    ``p:``-prefixed attributes on the same start tag. The expanded ``uri|local`` name
    of every attribute is built by expat before any handler runs."""
    head = f'<gpx xmlns:p="urn:{"u" * (uri_len - 4)}"'
    return (head + burst(' p:%s=""', size - len(head) - 2) + "/>").encode()


@cache
def xmlns_binding_burst(size: int, uri_len: int) -> bytes:
    """One element declaring distinct ``xmlns:NAME`` prefixes, all bound to one URI."""
    uri = "u" * uri_len
    return ("<gpx" + burst(' xmlns:%s="' + uri + '"', size - 8) + "/>").encode()


def wpt_with_prefixed_burst(size: int) -> bytes:
    """A skipped ``<wpt>`` carrying a prefixed-attribute burst (root binds ``p``)."""
    return ('<wpt lat="0" lon="0"' + burst(' p:%s=""', size) + "/>").encode()


def run_python(
    code: str,
    data: bytes = b"",
    *,
    flags: Sequence[str] = (),
    timeout_s: float = 120.0,
) -> subprocess.CompletedProcess[bytes]:
    """``code`` in a fresh isolated interpreter with ``api/`` importable; ``data`` on
    stdin. A hang fails the test; a crash or kill is a non-zero exit code."""
    prelude = f"import sys\nsys.path.insert(0, {str(API_DIR)!r})\n"
    try:
        return subprocess.run(
            [sys.executable, "-I", *flags, "-c", prelude + textwrap.dedent(code)],
            input=data,
            capture_output=True,
            timeout=timeout_s,
            cwd=API_DIR,
            check=False,
        )
    except subprocess.TimeoutExpired:
        import pytest  # here, so h_rows.py runs in an image that has no pytest

        pytest.fail(f"the child process did not finish within {timeout_s} s")


def last_json_line(result: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
    stderr = result.stderr.decode(errors="replace")[-800:]
    assert result.returncode == 0, (
        f"the child process died (exit {result.returncode}): {stderr}"
    )
    loaded = json.loads(result.stdout.decode().strip().splitlines()[-1])
    assert isinstance(loaded, dict)
    return loaded


# Reads the document from stdin, parses it with the defaults, and reports the outcome,
# the wall time and the peak-RSS growth over the process after its imports (so it
# includes the input bytes), as the ADR's P does.
MEASURED_PARSE_CHILD = """
    import json, time

    def peak_rss_bytes():
        try:
            import resource
        except ImportError:  # Windows
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD
            ]
            psapi.GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            )
            return counters.PeakWorkingSetSize
        if sys.platform == "darwin":
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux: VmHWM is this process's own high-water mark. ru_maxrss is not: exec
        # keeps the parent's high-water mark, so a child of a big pytest process read
        # a "baseline" above its own peak and every P came out 0.0 (vacuous bars).
        with open("/proc/self/status") as status:
            for line in status:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
        raise RuntimeError("no VmHWM in /proc/self/status")

    from app.routes.errors import RouteParseError
    from app.routes.parse import parse_gpx

    baseline = peak_rss_bytes()
    data = sys.stdin.buffer.read()
    started = time.perf_counter()
    message = None
    try:
        outcome = f"{len(parse_gpx(data).points)} points"
    except RouteParseError as exc:  # invalid_gpx, too_many_points, too_few_points
        outcome, message = exc.code, exc.message
    seconds = time.perf_counter() - started
    peak = peak_rss_bytes()
    print(json.dumps({
        "outcome": outcome, "message": message, "seconds": seconds,
        "p_mib": (peak - baseline) / (1024 * 1024),  # growth since the imports
        "rss_mib": peak / (1024 * 1024),  # the child's absolute high-water mark
    }))
"""
