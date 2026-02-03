"""Application configuration management."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "Zerg Rush"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # Cloud provider: gcp, aws, azure
    cloud_provider: Literal["gcp", "aws", "azure"] = "gcp"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/zergrush"

    # GCP-specific settings
    gcp_project_id: str | None = None
    gcp_region: str = "us-central1"
    gcp_zone: str = "us-central1-a"
    gcp_agent_network: str = "agent-network"
    gcp_agent_subnet: str = "agent-subnet"

    # OAuth (Google)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    oauth_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # Agent defaults
    default_vm_size: str = "e2-small"
    default_agent_platform: str = "openclaw"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
