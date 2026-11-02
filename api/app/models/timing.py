"""Response model for the duration estimator (ADR 0006 §6)."""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.routes.params import MAX_SUMMARY_POINTS


class Timing(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    start: AwareDatetime
    finish: AwareDatetime
    moving_min: Annotated[float, Field(ge=0)]
    total_min: Annotated[float, Field(ge=0)]
    eta_by_point: Annotated[
        list[AwareDatetime], Field(min_length=2, max_length=MAX_SUMMARY_POINTS)
    ]
