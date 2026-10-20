"""The whole pure pipeline: bytes in, RouteSummary out. The benchmark target."""

from app.models.route import LatLonElev, RouteSummary, TrackPoint
from app.routes.elevation import gain_loss, high_point_index, smooth_elevation
from app.routes.errors import TooFewPoints
from app.routes.geo import cumulative_distance, is_loop
from app.routes.naming import route_name
from app.routes.params import DEFAULT_PARAMS, ParseParams
from app.routes.parse import drop_consecutive_duplicates, parse_gpx
from app.routes.simplify import simplify


def summarise_gpx(
    data: bytes, filename: str | None, params: ParseParams = DEFAULT_PARAMS
) -> RouteSummary:
    """Raise RouteParseError only."""
    raw = parse_gpx(data)
    points = drop_consecutive_duplicates(raw.points)
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
        max_points=params.max_points,
        prethin_max_points=params.prethin_max_points,
        dist_m=dist,
    )
    return RouteSummary(
        name=route_name(raw.metadata_name, raw.track_name, filename),
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
        source_format=raw.source_format,
        point_count_original=len(raw.points),
    )
