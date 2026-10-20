"""Non-fatal findings returned alongside a result (ADR 0005 6)."""

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

WarningCode = Literal["elevation_unavailable"]
WarningSeverity = Literal["info", "warn", "danger"]


class ApiWarning(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: WarningCode
    severity: WarningSeverity
    message: Annotated[str, Field(min_length=1)]


ELEVATION_UNAVAILABLE: Final = ApiWarning(
    code="elevation_unavailable",
    severity="warn",
    message=(
        "Elevation could not be looked up, so gain, loss and the elevation "
        "profile are unavailable."
    ),
)
