from typing import Annotated, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings. Env vars: HIKE_ + upper-cased field name."""

    model_config = SettingsConfigDict(
        env_prefix="HIKE_", env_file=".env", extra="ignore"
    )

    env: str = "local"
    cors_origins: list[str] = ["http://localhost:5173"]
    cors_firebase_site: str | None = None
    version: str = "0.0.0-dev"
    git_sha: str = "unknown"
    open_meteo_base_url: str = "https://api.open-meteo.com"
    log_level: LogLevel = "INFO"
    elevation_timeout_s: Annotated[float, Field(gt=0, le=30)] = 5.0
