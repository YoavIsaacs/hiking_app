from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.cors import cors_policy
from app.errors import install_error_handlers
from app.logging_config import configure_logging
from app.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from app.operation_ids import check_operation_ids, operation_id
from app.routers import health, routes
from app.routes.params import MAX_CONCURRENT_PARSES


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own the elevation HTTP client (ADR 0005 4). Stub, not wired into FastAPI yet."""
    raise NotImplementedError
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    policy = cors_policy(settings.cors_origins, settings.cors_firebase_site)
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Hike Prep API",
        version=settings.version,
        generate_unique_id_function=operation_id,
    )
    app.state.settings = settings
    app.state.parse_limiter = anyio.CapacityLimiter(MAX_CONCURRENT_PARSES)
    app.state.elevation_lookup = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(policy.allow_origins),
        allow_origin_regex=policy.allow_origin_regex,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    # Added last so it is outermost: every response (incl. CORS preflights) gets an ID.
    app.add_middleware(RequestIdMiddleware)

    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(routes.router)
    check_operation_ids(app)
    return app
