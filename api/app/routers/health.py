from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings
from app.dependencies import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    git_sha: str
    env: str


@router.get("/health", response_model=HealthResponse, operation_id="getHealth")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.version,
        git_sha=settings.git_sha,
        env=settings.env,
    )
