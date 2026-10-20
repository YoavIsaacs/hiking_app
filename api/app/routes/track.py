"""Raw track data handed from the parser to the rest of the pipeline."""

from dataclasses import dataclass

from app.models.route import SourceFormat


@dataclass(frozen=True, slots=True)
class RawPoint:
    lat: float
    lon: float
    elev_m: float | None  # None: missing or non-finite <ele>


@dataclass(frozen=True, slots=True)
class RawTrack:
    # chosen source, merged in document order, validated, NOT de-duplicated
    points: tuple[RawPoint, ...]
    source_format: SourceFormat
    metadata_name: str | None
    track_name: str | None  # first non-blank <trk><name> (or <rte><name>), raw
