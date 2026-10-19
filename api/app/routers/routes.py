from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.body_limit import UploadLimitRoute
from app.errors import ERROR_RESPONSES
from app.models.route import RouteSummary

router = APIRouter(prefix="/v1/routes", tags=["routes"], route_class=UploadLimitRoute)


@router.post(
    "/parse",
    responses=ERROR_RESPONSES,
    summary="Parse a GPX file into a route summary",
)
async def parse_route(
    file: Annotated[UploadFile, File(description="GPX 1.0/1.1 file, at most 10 MB")],
) -> RouteSummary:
    # Contract: read(MAX_UPLOAD_BYTES + 1) -> 413 | run_in_threadpool(summarise_gpx)
    # RouteParseError -> ApiError(422, e.code, e.message)
    raise NotImplementedError
