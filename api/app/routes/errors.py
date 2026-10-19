"""Domain errors of the GPX pipeline; the router maps them to HTTP."""

from typing import ClassVar, Literal


class RouteParseError(Exception):
    code: ClassVar[Literal["invalid_gpx", "too_few_points"]]

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._message = message

    @property
    def message(self) -> str:
        return self._message


class InvalidGpx(RouteParseError):
    code = "invalid_gpx"


class TooFewPoints(RouteParseError):
    code = "too_few_points"
