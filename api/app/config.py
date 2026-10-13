from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings. Env vars are the upper-cased field names, no prefix."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    cors_origins: list[str] = ["http://localhost:5173"]
    version: str = "0.0.0-dev"
    git_sha: str = "unknown"
    open_meteo_base_url: str = "https://api.open-meteo.com"
    log_level: LogLevel = "INFO"
