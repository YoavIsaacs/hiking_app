from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.logging_config import configure_logging
from app.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from app.routers import health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Hike Prep API", version=settings.version)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    # Added last so it is outermost: every response (incl. CORS preflights) gets an ID.
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health.router)
    return app
