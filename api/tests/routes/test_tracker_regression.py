"""The review round-3 regression, in a child process (ADR 0004 3.13, rows H2 and H3).

One ``<gpx>`` start tag that binds a prefix to a long URI and then carries about a
million distinct prefixed attributes, 10 MiB in all. Expat builds ``uri|local`` for
every attribute before any handler runs: untracked, the tech lead's image was
OOM-killed (exit 137) under ``--memory=512m``.

Each shape runs in a fresh interpreter, so a MemoryError, a crash or a kill fails one
test instead of taking pytest down. The ceilings are the ADR's: P (the child's peak-RSS
growth over its own post-import baseline, input bytes included) at most 120 MiB, and
a wall time of a few seconds.

Sizes: both shapes are the full 10 MiB the upload cap allows. The attribute shape uses
a 256-byte URI, not the 1 MiB one the ADR lists: shortest-first names fill 10 MiB with
about a million attributes, and 256 bytes already makes the untracked parse allocate
about 500 MiB (measured with ``tracemalloc`` at 4 MiB: 209 MiB, linear in size), which
is 4x the ceiling, while a 1 MiB URI would make a failing run (no tracker) try to
allocate hundreds of GiB on a developer machine. The binding shape uses a 1-byte URI,
because bindings only amplify when the URI is short (a 256-byte URI makes the bindings
mostly URI, with no amplification); untracked it is about 200 MiB at 10 MiB.
"""

import pytest

from app.routes.params import MAX_UPLOAD_BYTES
from tests.routes.hostile_shapes import (
    MEASURED_PARSE_CHILD,
    last_json_line,
    prefixed_attribute_burst,
    run_python,
    xmlns_binding_burst,
)

P_CEILING_MIB = 120.0  # ADR 3.13: P <= 120 MiB, i.e. RSS high-water <= 160 MiB
P_FLOOR_MIB = 9.0  # P includes the 10 MiB of input; a 0.0 means the measure is broken
SECONDS_CEILING = 5.0  # ADR: <= 3.5 s in the image; CI runners get headroom

SHAPES = {
    "round-3: prefix bound to a 256 B URI, then distinct prefixed attributes": (
        lambda: prefixed_attribute_burst(MAX_UPLOAD_BYTES, 256)
    ),
    "distinct xmlns:NAME declarations bound to a 1 B URI": (
        lambda: xmlns_binding_burst(MAX_UPLOAD_BYTES, 1)
    ),
}


@pytest.mark.parametrize("shape", list(SHAPES))
def test_a_10_mib_hostile_start_tag_is_refused_quickly_in_bounded_memory(
    shape: str,
) -> None:
    data = SHAPES[shape]()
    assert MAX_UPLOAD_BYTES - 64 <= len(data) <= MAX_UPLOAD_BYTES
    out = last_json_line(run_python(MEASURED_PARSE_CHILD, data, timeout_s=120))
    assert out["outcome"] == "invalid_gpx", out
    assert out["message"] == "The file is too complex to parse.", out
    seconds, grown = out["seconds"], out["p_mib"]
    assert isinstance(seconds, float) and seconds <= SECONDS_CEILING, out
    assert isinstance(grown, float) and P_FLOOR_MIB <= grown <= P_CEILING_MIB, out
