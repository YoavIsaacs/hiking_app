"""Response models for route parsing (ADR 0004 §2). All fields are required."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.warnings import ApiWarning
from app.routes.params import MAX_NAME_LENGTH, MAX_SUMMARY_POINTS

Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
NonNegMetres = Annotated[float, Field(ge=0)]
SourceFormat = Literal["trk", "rte"]
ElevationSource = Literal["file", "lookup", "none"]

_CONFIG = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class LatLonElev(BaseModel):
    model_config = _CONFIG

    lat: Latitude
    lon: Longitude
    elev_m: float | None


class TrackPoint(BaseModel):
    model_config = _CONFIG

    lat: Latitude
    lon: Longitude
    elev_m: float | None
    dist_m: NonNegMetres


class RouteSummary(BaseModel):
    model_config = _CONFIG

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH)]
    distance_m: NonNegMetres
    gain_m: NonNegMetres | None
    loss_m: NonNegMetres | None
    min_elev_m: float | None
    max_elev_m: float | None
    high_point: LatLonElev | None
    start: LatLonElev
    end: LatLonElev
    is_loop: bool
    points: Annotated[
        list[TrackPoint], Field(min_length=2, max_length=MAX_SUMMARY_POINTS)
    ]
    has_elevation: bool
    elevation_source: ElevationSource
    source_format: SourceFormat
    point_count_original: Annotated[int, Field(ge=2)]
    warnings: list[ApiWarning]
