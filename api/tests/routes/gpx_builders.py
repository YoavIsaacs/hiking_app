"""Synthetic GPX construction for the route tests.

Everything here is test-side: the geometry (destination point, haversine) is
written independently of ``app.routes`` so the tests are an oracle, not a copy.
Only the Earth radius, fixed by ADR 0004 section 3.3, is shared.
"""

import math
from collections.abc import Sequence
from typing import Literal, NamedTuple

from app.routes.params import EARTH_RADIUS_M

Kind = Literal["trk", "rte"]


class Pt(NamedTuple):
    lat: float
    lon: float
    ele: float | None


DEFAULT_START = Pt(31.9, 34.9, 100.0)


def haversine_m(a: Pt, b: Pt) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi = p2 - p1
    dlmb = math.radians(b.lon) - math.radians(a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def destination(p: Pt, bearing_deg: float, distance_m: float) -> Pt:
    """Point ``distance_m`` from ``p`` along ``bearing_deg``; keeps ``p.ele``."""
    phi1, lmb1 = math.radians(p.lat), math.radians(p.lon)
    theta, delta = math.radians(bearing_deg), distance_m / EARTH_RADIUS_M
    sin_phi2 = math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(
        delta
    ) * math.cos(theta)
    phi2 = math.asin(max(-1.0, min(1.0, sin_phi2)))
    lmb2 = lmb1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * sin_phi2,
    )
    lon = (math.degrees(lmb2) + 540.0) % 360.0 - 180.0
    return Pt(math.degrees(phi2), lon, p.ele)


def path_length_m(points: Sequence[Pt]) -> float:
    return math.fsum(
        haversine_m(a, b) for a, b in zip(points, points[1:], strict=False)
    )


def dedupe(points: Sequence[Pt]) -> list[Pt]:
    """Drop consecutive points with exactly equal (lat, lon); keep the first."""
    out: list[Pt] = []
    for p in points:
        if not out or (out[-1].lat, out[-1].lon) != (p.lat, p.lon):
            out.append(p)
    return out


def straight_line(
    n: int,
    *,
    start: Pt = DEFAULT_START,
    bearing_deg: float = 0.0,
    step_m: float = 20.0,
    ele: float | None = 100.0,
) -> list[Pt]:
    pts = [Pt(start.lat, start.lon, ele)]
    for _ in range(n - 1):
        pts.append(destination(pts[-1], bearing_deg, step_m))
    return pts


def out_and_back(
    out_m: float = 2000.0, step_m: float = 20.0, offset_m: float = 10.0
) -> list[Pt]:
    """Out along bearing 0, back on a path offset by ``offset_m`` to the east."""
    out = straight_line(round(out_m / step_m) + 1, step_m=step_m)
    turn = destination(out[-1], 90.0, offset_m)
    back = [destination(p, 90.0, offset_m) for p in reversed(out)]
    return [*out, turn, *back]


def _xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _point_xml(tag: str, p: Pt, time: str | None) -> str:
    ele = "" if p.ele is None else f"<ele>{p.ele!r}</ele>"
    when = "" if time is None else f"<time>{time}</time>"
    return f'<{tag} lat="{p.lat!r}" lon="{p.lon!r}">{ele}{when}</{tag}>'


def gpx_bytes(
    segments: Sequence[Sequence[Pt]],
    *,
    kind: Kind = "trk",
    metadata_name: str | None = None,
    track_names: Sequence[str | None] = (),
    version: Literal["1.0", "1.1", "none"] = "1.1",
    bom: bool = False,
    times: bool = False,
    extra_after_root: str = "",
) -> bytes:
    """A GPX document. ``trk``: one <trk> holding every segment (or one per
    entry of ``track_names``); ``rte``: one <rte> holding all points."""
    if version == "1.1":
        root = (
            '<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
        )
    elif version == "1.0":
        root = (
            '<gpx version="1.0" creator="t" xmlns="http://www.topografix.com/GPX/1/0">'
        )
    else:
        root = "<gpx>"
    body: list[str] = []
    if metadata_name is not None:
        body.append(f"<metadata><name>{_xml_text(metadata_name)}</name></metadata>")
    counter = 0

    def stamp() -> str | None:
        nonlocal counter
        if not times:
            return None
        counter += 1
        return f"2026-03-29T02:{counter % 60:02d}:00+03:00"

    if kind == "rte":
        pts = "".join(_point_xml("rtept", p, stamp()) for seg in segments for p in seg)
        name = (
            f"<name>{_xml_text(track_names[0])}</name>"
            if track_names and track_names[0] is not None
            else ""
        )
        body.append(f"<rte>{name}{pts}</rte>")
    elif track_names:
        for tname, seg in zip(track_names, segments, strict=True):
            name = "" if tname is None else f"<name>{_xml_text(tname)}</name>"
            pts = "".join(_point_xml("trkpt", p, stamp()) for p in seg)
            body.append(f"<trk>{name}<trkseg>{pts}</trkseg></trk>")
    else:
        segs = "".join(
            "<trkseg>"
            + "".join(_point_xml("trkpt", p, stamp()) for p in seg)
            + "</trkseg>"
            for seg in segments
        )
        body.append(f"<trk>{segs}</trk>")
    prolog = '<?xml version="1.0" encoding="UTF-8"?>'
    text = f"{prolog}{root}{''.join(body)}</gpx>{extra_after_root}"
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


def add_rte(data: bytes, points: Sequence[Pt]) -> bytes:
    """Insert one <rte> holding ``points`` just before the closing </gpx>."""
    rte = "<rte>" + "".join(_point_xml("rtept", p, None) for p in points) + "</rte>"
    return data.replace(b"</gpx>", rte.encode("utf-8") + b"</gpx>")
