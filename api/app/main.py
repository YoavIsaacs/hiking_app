from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.cors import cors_policy
from app.logging_config import configure_logging
from app.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from app.operation_ids import check_operation_ids, operation_id
from app.routers import health


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

    app.include_router(health.router)
    check_operation_ids(app)
    return app
