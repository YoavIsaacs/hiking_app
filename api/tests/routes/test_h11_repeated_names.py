"""ADR 0004 3.13 rows H11 and H12, and the P measurement they rely on.

H11 is the admitted worst case for time: one name repeated to fill 10 MiB at the
largest admitted namespace URI (256 ASCII characters). The tracker never refuses a
repeated name, so these are 200s; the bars are the memory ceiling and the wall time.
(d), a non-ASCII local name under the default namespace, is the slowest of them and
the reason S = 2.6 s (item 52); it was measured by hand until now.

The bar is 3.5 s in the production image on a quiet host. Here the ceiling is looser
because this runs on whatever machine runs pytest (natively on Windows (d) takes
3.5 to 4.5 s). ``h_rows.py`` is the harness that measures the real bar in the image.

H12 is the same shapes one step over the cap: refused at the root's declaration.
"""

import pytest

from tests.routes.h_rows import (
    FOUR_BYTE,
    SIZE,
    TOO_COMPLEX,
    h11,
    h12,
    round4_file,
    uri,
)
from tests.routes.hostile_shapes import (
    MEASURED_PARSE_CHILD,
    MIB,
    last_json_line,
    run_python,
)

P_CEILING_MIB = 120.0  # ADR 3.13: P <= 120 MiB, i.e. RSS high-water <= 160 MiB
SECONDS_CEILING = 8.0  # ADR: <= 3.5 s in the image; any pytest host gets headroom
P_FLOOR_MIB = 9.0  # P includes the 10 MiB of input bytes the child reads


def measure(data: bytes) -> dict[str, object]:
    assert SIZE - 64 <= len(data) <= SIZE
    return last_json_line(run_python(MEASURED_PARSE_CHILD, data, timeout_s=120))


def check_memory(out: dict[str, object]) -> None:
    grown = out["p_mib"]
    assert isinstance(grown, float), out
    assert P_FLOOR_MIB <= grown <= P_CEILING_MIB, out


@pytest.mark.parametrize("shape", ["a", "b", "c", "d"])
def test_h11_a_repeated_name_at_the_largest_uri_is_admitted_in_bounded_memory_and_time(
    shape: str,
) -> None:
    out = measure(h11(shape))
    assert out["outcome"] == "2 points", out
    seconds = out["seconds"]
    assert isinstance(seconds, float) and seconds <= SECONDS_CEILING, out
    check_memory(out)


def test_h11_d_is_a_non_ascii_local_name_not_an_ascii_one() -> None:
    data = h11("d")
    assert "Ā".encode() in data and b"<a/>" not in data.split(b"<trk>")[0]
    assert data.startswith(f'<gpx xmlns="{uri(256)}">'.encode())


@pytest.mark.parametrize("shape", ["a", "b", "c"])
@pytest.mark.parametrize(
    "declared", [uri(257), FOUR_BYTE], ids=["257 ASCII characters", "one U+10000"]
)
def test_h12_the_same_shapes_over_the_cap_are_refused_at_the_declaration(
    shape: str, declared: str
) -> None:
    out = measure(h12(shape, declared))
    assert out["outcome"] == "invalid_gpx", out
    assert out["message"] == TOO_COMPLEX, out
    seconds = out["seconds"]
    assert isinstance(seconds, float) and seconds < 1.0, out
    check_memory(out)


def test_h12_the_round_4_file_is_refused_at_the_declaration() -> None:
    out = measure(round4_file())
    assert out["outcome"] == "invalid_gpx" and out["message"] == TOO_COMPLEX, out
    seconds = out["seconds"]
    assert isinstance(seconds, float) and seconds < 1.0, out


# --- the P measurement (reads 0.0 on Linux in 1.2) ----------------------------------


def test_p_is_a_real_measurement_even_when_the_parent_process_is_big() -> None:
    """On Linux ``ru_maxrss`` survives exec, so a child of a process that once used
    more memory than the child ever will read a baseline above its own peak and P came
    out 0.0: every "P <= ceiling" bar passed vacuously. P must include at least the
    10 MiB document the child reads, whatever its parent looks like."""
    ballast = bytearray(300 * MIB)
    for offset in range(0, len(ballast), 4096):
        ballast[offset] = 1  # touch every page so the parent's high-water mark is real
    try:
        out = measure(h11("a"))
    finally:
        del ballast
    check_memory(out)
    rss = out["rss_mib"]
    assert isinstance(rss, float) and rss >= SIZE / MIB, out
