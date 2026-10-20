"""Typed Hypothesis strategies for random tracks (ADR 0004, "Hypothesis properties")."""

import random
from dataclasses import dataclass
from typing import Literal

from hypothesis import strategies as st

from tests.routes.gpx_builders import Kind, Pt, destination, gpx_bytes, haversine_m

ElevationMode = Literal["all", "none", "partial"]


@dataclass(frozen=True)
class Track:
    kind: Kind
    segments: tuple[tuple[Pt, ...], ...]
    elevation: ElevationMode

    def gpx(self) -> bytes:
        return gpx_bytes(self.segments, kind=self.kind)

    def reversed(self) -> "Track":
        return Track(
            self.kind,
            tuple(tuple(reversed(seg)) for seg in reversed(self.segments)),
            self.elevation,
        )

    @property
    def flat(self) -> list[Pt]:
        return [p for seg in self.segments for p in seg]


@st.composite
def tracks(draw: st.DrawFn, *, min_points: int = 2, max_points: int = 200) -> Track:
    """2-200 points: a start anywhere (poles, antimeridian), then steps of
    0-500 m on random bearings, random duplicates, finite elevations -400..8848 m and
    optionally missing <ele>; written as trk, rte or multi-segment trk."""
    n = draw(st.integers(min_points, max_points))
    lat = draw(
        st.one_of(
            st.floats(-89.9, 89.9),
            st.sampled_from([89.9, -89.9, 0.0, 31.9]),
        )
    )
    lon = draw(
        st.one_of(
            st.floats(-180.0, 180.0),
            st.sampled_from([180.0, -180.0, 179.9999, -179.9999, 0.0]),
        )
    )
    elevation: ElevationMode = draw(
        st.sampled_from(["all", "all", "all", "none", "partial"])
    )
    elevations = draw(
        st.lists(
            st.integers(-40000, 884800).map(lambda c: c / 100), min_size=n, max_size=n
        )
    )
    steps = draw(st.lists(st.floats(0.0, 500.0), min_size=n, max_size=n))
    bearings = draw(st.lists(st.floats(0.0, 360.0), min_size=n, max_size=n))
    dupes = draw(st.lists(st.booleans(), min_size=n, max_size=n))
    missing = draw(st.lists(st.booleans(), min_size=n, max_size=n))

    def ele(i: int) -> float | None:
        if elevation == "none":
            return None
        if elevation == "partial" and missing[i]:
            return None
        return elevations[i]

    points = [Pt(lat, lon, ele(0))]
    for i in range(1, n):
        prev = points[-1]
        moved = prev if dupes[i] else destination(prev, bearings[i], steps[i])
        if haversine_m(prev, moved) < 1e-3:
            # sub-millimetre steps are float noise, not distinct points: snap to a
            # true duplicate so de-duplication (not distance smoothing) handles them
            moved = prev
        # Points sharing (lat, lon) share <ele>: ADR 0004 3.2 keeps the first of a
        # duplicate run, so differing elevations would break forward/reverse symmetry.
        same_spot = (moved.lat, moved.lon) == (prev.lat, prev.lon)
        points.append(Pt(moved.lat, moved.lon, prev.ele if same_spot else ele(i)))
    kind: Kind = draw(st.sampled_from(["trk", "trk", "rte"]))
    cuts: list[int] = []
    if kind == "trk":
        cuts = sorted(set(draw(st.lists(st.integers(1, max(1, n - 1)), max_size=3))))
    bounds = [0, *[c for c in cuts if 0 < c < n], n]
    segments = tuple(
        tuple(points[a:b]) for a, b in zip(bounds, bounds[1:], strict=False)
    )
    return Track(kind, segments, elevation)


LongShape = Literal["walk", "zigzag", "line"]


def long_track(
    n: int, seed: int, shape: LongShape, elevation: ElevationMode = "all"
) -> Track:
    """``n`` distinct points (steps of 2-60 m, so no de-duplication), one segment.

    Built from a seeded ``random.Random`` so a failing example reproduces from its
    three small parameters; Hypothesis shrinks ``n``, ``seed`` and ``shape`` instead of
    thousands of drawn floats."""
    rng = random.Random(seed)
    lat = rng.uniform(-80.0, 80.0)
    lon = rng.uniform(-179.0, 179.0)

    def ele() -> float | None:
        return None if elevation == "none" else rng.randrange(-40_000, 884_800) / 100

    points = [Pt(lat, lon, ele())]
    for i in range(1, n):
        step = rng.uniform(2.0, 60.0)
        if shape == "walk":
            bearing = rng.uniform(0.0, 360.0)
        elif shape == "zigzag":
            bearing = 45.0 if i % 2 else 135.0
        else:
            bearing = 20.0
        moved = destination(points[-1], bearing, step)
        points.append(Pt(moved.lat, moved.lon, ele()))
    return Track("trk", (tuple(points),), elevation)


@st.composite
def long_tracks(draw: st.DrawFn) -> Track:
    """501-2,500 points: crosses the 500-point simplify threshold and the 2,000-point
    pre-thinning threshold (ADR 0004 3.5), which ``tracks()`` (<= 200) never reaches."""
    return long_track(
        draw(st.integers(501, 2500)),
        draw(st.integers(0, 2**32 - 1)),
        draw(st.sampled_from(["walk", "zigzag", "line"])),
        draw(st.sampled_from(["all", "all", "none"])),
    )
