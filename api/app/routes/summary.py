"""The pure pipeline stages: bytes in, RouteSummary out (ADR 0005 1).

`summarise_gpx` is the whole pure pipeline and the benchmark target.
"""

import math
from collections.abc import Sequence

from app.models.route import LatLonElev, RouteSummary, TrackPoint
from app.models.warnings import ApiWarning
from app.routes.elevation import gain_loss, high_point_index, smooth_elevation
from app.routes.errors import TooFewPoints
from app.routes.geo import cumulative_distance, is_loop
from app.routes.naming import route_name
from app.routes.params import (
    DEFAULT_PARAMS,
    MAX_PLAUSIBLE_ELEV_M,
    MIN_PLAUSIBLE_ELEV_M,
    ParseParams,
)
from app.routes.parse import drop_consecutive_duplicates, parse_gpx
from app.routes.simplify import simplify
from app.routes.track import RawTrack


def lookup_point_count(distance_m: float, params: ParseParams = DEFAULT_PARAMS) -> int:
    """How many points a no-elevation route is simplified to (ADR 0005 5).

    The cap when lookup_spacing_m is 0, else about one point per spacing, in 3..cap.
    """
    cap = min(params.max_points, params.lookup_max_points)
    if params.lookup_spacing_m == 0:
        return cap
    spans = (
        distance_m / params.lookup_spacing_m
    )  # may be huge or inf for a tiny spacing
    if spans >= cap:
        return cap
    return min(cap, max(3, math.ceil(spans) + 1))


def summarise_gpx(
    data: bytes, filename: str | None, params: ParseParams = DEFAULT_PARAMS
) -> RouteSummary:
    """Raise RouteParseError only."""
    return summarise_track(parse_gpx(data), filename, params)


def summarise_track(
    track: RawTrack, filename: str | None, params: ParseParams = DEFAULT_PARAMS
) -> RouteSummary:
    """Stage 1 (ADR 0005 1). Raise RouteParseError only; never looks anything up.

    Without elevation the points are simplified horizontally to lookup_point_count,
    and are exactly the points a lookup should cover.
    """
    points = drop_consecutive_duplicates(track.points)
    if len(points) < 2:
        raise TooFewPoints("The file has fewer than 2 distinct track points.")

    dist = cumulative_distance(points)
    elevations = [p.elev_m for p in points]
    profile = [e for e in elevations if e is not None]
    has_elevation = len(profile) == len(points)

    gain: float | None = None
    loss: float | None = None
    min_elev: float | None = None
    max_elev: float | None = None
    keep: list[int] = []
    if has_elevation:
        smoothed = smooth_elevation(
            dist,
            profile,
            window_m=params.smoothing_window_m,
            step_m=params.resample_step_m,
            max_samples=params.max_resample_points,
        )
        gain, loss = gain_loss(smoothed, threshold_m=params.gain_threshold_m)
        min_elev, max_elev = min(profile), max(profile)
        keep.append(high_point_index(profile))

    def at(i: int) -> LatLonElev:
        p = points[i]
        return LatLonElev(
            lat=p.lat, lon=p.lon, elev_m=p.elev_m if has_elevation else None
        )

    kept = simplify(
        points,
        keep=keep,
        max_points=(
            params.max_points if has_elevation else lookup_point_count(dist[-1], params)
        ),
        prethin_max_points=params.prethin_max_points,
        dist_m=dist,
    )
    return RouteSummary(
        name=route_name(track.metadata_name, track.track_name, filename),
        distance_m=dist[-1],
        gain_m=gain,
        loss_m=loss,
        min_elev_m=min_elev,
        max_elev_m=max_elev,
        high_point=at(keep[0]) if keep else None,
        start=at(0),
        end=at(len(points) - 1),
        is_loop=is_loop(points[0], points[-1], threshold_m=params.loop_threshold_m),
        points=[
            TrackPoint(
                lat=points[i].lat,
                lon=points[i].lon,
                elev_m=points[i].elev_m if has_elevation else None,
                dist_m=dist[i],
            )
            for i in kept
        ],
        has_elevation=has_elevation,
        elevation_source="file" if has_elevation else "none",
        source_format=track.source_format,
        point_count_original=len(track.points),
        warnings=[],
    )


def with_looked_up_elevation(
    summary: RouteSummary,
    elevations: Sequence[float],
    params: ParseParams = DEFAULT_PARAMS,
) -> RouteSummary:
    """Stage 3 (ADR 0005 3): fill in looked-up elevation and recompute everything.

    Raise ValueError if the summary is not a no-elevation one, the count differs from
    its points, or a value is non-finite or implausible.
    """
    if summary.elevation_source != "none":
        raise ValueError("only a summary without elevation can be filled in")
    if len(elevations) != len(summary.points):
        raise ValueError(
            f"expected {len(summary.points)} elevations, got {len(elevations)}"
        )
    if not all(
        math.isfinite(e) and MIN_PLAUSIBLE_ELEV_M <= e <= MAX_PLAUSIBLE_ELEV_M
        for e in elevations
    ):
        raise ValueError("an elevation is non-finite or outside the plausible range")

    smoothed = smooth_elevation(
        [p.dist_m for p in summary.points],
        elevations,
        window_m=params.lookup_smoothing_window_m,
        step_m=params.resample_step_m,
        max_samples=params.max_resample_points,
    )
    gain, loss = gain_loss(smoothed, threshold_m=params.lookup_gain_threshold_m)
    points = [
        TrackPoint(lat=p.lat, lon=p.lon, elev_m=e, dist_m=p.dist_m)
        for p, e in zip(summary.points, elevations, strict=True)
    ]
    top = points[high_point_index(elevations)]
    return summary.model_copy(
        update={
            "points": points,
            "start": LatLonElev(
                lat=points[0].lat, lon=points[0].lon, elev_m=points[0].elev_m
            ),
            "end": LatLonElev(
                lat=points[-1].lat, lon=points[-1].lon, elev_m=points[-1].elev_m
            ),
            "high_point": LatLonElev(lat=top.lat, lon=top.lon, elev_m=top.elev_m),
            "min_elev_m": min(elevations),
            "max_elev_m": max(elevations),
            "gain_m": gain,
            "loss_m": loss,
            "has_elevation": True,
            "elevation_source": "lookup",
            "warnings": [],
        }
    )


def with_warning(summary: RouteSummary, warning: ApiWarning) -> RouteSummary:
    """Append a warning; nothing else changes (ADR 0005 6)."""
    return summary.model_copy(update={"warnings": [*summary.warnings, warning]})
