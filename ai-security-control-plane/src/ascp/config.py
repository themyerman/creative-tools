"""Application settings (ASCP_* env vars)."""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./ascp.db"
    artifact_root: str = "./ascp_artifacts"
    log_level: str = "INFO"
    # If set, all routes except /health require Authorization: Bearer <key> or X-ASCP-API-Key
    api_key: Optional[str] = None

    # Gateway: forward allowed chat/completions to OpenAI-compatible upstream
    upstream_base_url: Optional[str] = None  # e.g. https://api.openai.com/v1
    upstream_api_key: Optional[str] = None
    gateway_timeout_seconds: float = 120.0

    # Assurance live runs: optional default Authorization header for target_url calls
    assurance_target_default_authorization: Optional[str] = None
    assurance_http_timeout_seconds: float = 60.0
