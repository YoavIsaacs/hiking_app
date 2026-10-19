"""The whole pure pipeline: bytes in, RouteSummary out. The benchmark target."""

from app.models.route import RouteSummary
from app.routes.params import DEFAULT_PARAMS, ParseParams


def summarise_gpx(
    data: bytes, filename: str | None, params: ParseParams = DEFAULT_PARAMS
) -> RouteSummary:
    """Raise RouteParseError only."""
    raise NotImplementedError
