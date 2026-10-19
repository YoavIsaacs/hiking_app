"""GPX bytes to RawTrack. The only module that imports gpxpy (ADR 0004 §3.1, §3.2)."""

import math
from collections.abc import Iterable, Sequence

import gpxpy
from gpxpy.gpx import GPX, GPXRoutePoint, GPXTrackPoint

from app.models.route import SourceFormat
from app.routes.errors import InvalidGpx
from app.routes.track import RawPoint, RawTrack
from app.routes.xml_guard import check_gpx_prolog

_GpxPoint = GPXTrackPoint | GPXRoutePoint


def _first_non_blank(names: Iterable[str | None]) -> str | None:
    for name in names:
        if name is not None and name.strip():
            return name
    return None


def _choose_source(
    track_points: list[_GpxPoint], route_points: list[_GpxPoint]
) -> SourceFormat:
    if len(track_points) >= 2:
        return "trk"
    if len(route_points) >= 2:
        return "rte"
    return "rte" if len(route_points) > len(track_points) else "trk"


def _to_raw_point(point: _GpxPoint) -> RawPoint:
    lat, lon = point.latitude, point.longitude
    if lat is None or lon is None:
        raise InvalidGpx("A track point has no latitude or longitude.")
    if not (math.isfinite(lat) and -90.0 <= lat <= 90.0):
        raise InvalidGpx("A track point has a latitude outside -90..90.")
    if not (math.isfinite(lon) and -180.0 <= lon <= 180.0):
        raise InvalidGpx("A track point has a longitude outside -180..180.")
    ele = point.elevation
    return RawPoint(lat, lon, ele if ele is not None and math.isfinite(ele) else None)


def parse_gpx(data: bytes) -> RawTrack:
    """Raise InvalidGpx only."""
    if not data:
        raise InvalidGpx("The file is empty.")
    check_gpx_prolog(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidGpx("The file must be UTF-8 encoded.") from exc
    try:
        gpx: GPX = gpxpy.parse(text)
    except (
        Exception
    ) as exc:  # third-party parser of untrusted input; wraps only this call
        raise InvalidGpx(
            f"The file could not be parsed as GPX ({type(exc).__name__})."
        ) from exc

    track_points: list[_GpxPoint] = [
        p for trk in gpx.tracks for seg in trk.segments for p in seg.points
    ]
    route_points: list[_GpxPoint] = [p for rte in gpx.routes for p in rte.points]
    source = _choose_source(track_points, route_points)
    chosen = track_points if source == "trk" else route_points
    track_name = (
        _first_non_blank(trk.name for trk in gpx.tracks)
        if source == "trk"
        else _first_non_blank(rte.name for rte in gpx.routes)
    )
    return RawTrack(
        points=tuple(_to_raw_point(p) for p in chosen),
        source_format=source,
        metadata_name=gpx.name,
        track_name=track_name,
    )


def drop_consecutive_duplicates(points: Sequence[RawPoint]) -> tuple[RawPoint, ...]:
    """Drop points whose (lat, lon) equals the previous kept point's; first one wins."""
    out: list[RawPoint] = []
    for p in points:
        if not out or (out[-1].lat, out[-1].lon) != (p.lat, p.lon):
            out.append(p)
    return tuple(out)
