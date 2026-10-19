from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool

from app.body_limit import UploadLimitRoute, too_large
from app.errors import ERROR_RESPONSES, ApiError
from app.models.route import RouteSummary
from app.routes.errors import RouteParseError
from app.routes.params import MAX_UPLOAD_BYTES
from app.routes.summary import summarise_gpx

router = APIRouter(prefix="/v1/routes", tags=["routes"], route_class=UploadLimitRoute)


@router.post(
    "/parse",
    responses=ERROR_RESPONSES,
    summary="Parse a GPX file into a route summary",
)
async def parse_route(
    file: Annotated[UploadFile, File(description="GPX 1.0/1.1 file, at most 10 MB")],
) -> RouteSummary:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise too_large()
    try:
        return await run_in_threadpool(summarise_gpx, data, file.filename)
    except RouteParseError as exc:
        raise ApiError(422, exc.code, exc.message) from exc
