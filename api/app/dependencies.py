import anyio
from fastapi import Request

from app.config import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_parse_limiter(request: Request) -> anyio.CapacityLimiter:
    limiter: anyio.CapacityLimiter = request.app.state.parse_limiter
    return limiter
