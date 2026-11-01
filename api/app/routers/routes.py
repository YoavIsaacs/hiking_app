from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, File, UploadFile

from app.body_limit import UploadLimitRoute, too_large
from app.clients.elevation import ElevationLookup
from app.dependencies import get_elevation_lookup, get_parse_limiter
from app.errors import ERROR_RESPONSES, ApiError
from app.models.route import RouteSummary
from app.routes.errors import RouteParseError
from app.routes.params import MAX_UPLOAD_BYTES
from app.services.route_parse import summarise_upload

router = APIRouter(prefix="/v1/routes", tags=["routes"], route_class=UploadLimitRoute)


@router.post(
    "/parse",
    responses=ERROR_RESPONSES,
    summary="Parse a GPX file into a route summary",
)
async def parse_route(
    file: Annotated[UploadFile, File(description="GPX 1.0/1.1 file, at most 10 MB")],
    limiter: Annotated[anyio.CapacityLimiter, Depends(get_parse_limiter)],
    elevation: Annotated[ElevationLookup | None, Depends(get_elevation_lookup)],
) -> RouteSummary:
    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        # Free the spool now, so a request waiting for the limiter holds one copy
        # of the upload, not two (ADR 0004 3.10).
        await file.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise too_large()
    try:
        return await summarise_upload(
            data, file.filename, limiter=limiter, elevation=elevation
        )
    except RouteParseError as exc:
        raise ApiError(422, exc.code, exc.message) from exc
