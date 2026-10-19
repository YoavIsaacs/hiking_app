"""GPX bytes to RawTrack. The only module that imports gpxpy."""

from collections.abc import Sequence

from app.routes.track import RawPoint, RawTrack


def parse_gpx(data: bytes) -> RawTrack:
    """Raise InvalidGpx only."""
    raise NotImplementedError


def drop_consecutive_duplicates(points: Sequence[RawPoint]) -> tuple[RawPoint, ...]:
    raise NotImplementedError
