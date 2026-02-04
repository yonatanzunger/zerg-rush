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

    # Token encryption key for OAuth tokens (Fernet key, generate with Fernet.generate_key())
    # If not set, derives from secret_key (less secure, use explicit key in production)
    token_encryption_key: str | None = None

    # Cloud provider: gcp, aws, azure
    cloud_provider: Literal["gcp", "aws", "azure"] = "gcp"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/zergrush"

    # GCP-specific settings
    gcp_project_id: str | None = None
    gcp_region: str = "us-central1"
    gcp_zone: str = "us-central1-a"
    gcp_compute_type: Literal["cloudrun", "gce"] = (
        "cloudrun"  # cloudrun (containers) or gce (VMs)
    )
    gcp_agent_network: str = "default"  # For GCE VMs; "default" or a custom VPC
    gcp_agent_subnet: str = "default"  # For GCE VMs; "default" or a custom subnet
    # Service account email for IAM signing (used when signing URLs with user credentials)
    gcp_service_account_email: str | None = None

    # Cloud Run specific settings
    gcp_vpc_connector: str | None = (
        None  # e.g., "projects/PROJECT/locations/REGION/connectors/CONNECTOR"
    )
    agent_container_image: str | None = None  # Custom agent container image

    # Azure-specific settings
    azure_subscription_id: str | None = None
    azure_resource_group: str | None = None
    azure_location: str = "eastus"
    azure_compute_type: Literal["aci", "vm"] = "aci"  # aci (containers) or vm (VMs)
    azure_storage_account: str | None = None
    azure_keyvault_name: str | None = None
    azure_container_registry: str | None = None

    # Azure VNet settings for ACI (optional but recommended for security)
    azure_vnet_name: str | None = None
    azure_subnet_name: str | None = None

    # OAuth (Azure AD/Entra ID)
    azure_client_id: str | None = None
    azure_client_secret: str | None = None
    azure_tenant_id: str = (
        "common"  # Use "common" for multi-tenant or specific tenant ID
    )

    # OAuth (Google)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    oauth_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Allowed OAuth redirect URIs (whitelist for security)
    # Comma-separated list of allowed redirect URIs
    # If empty, only oauth_redirect_uri is allowed
    allowed_oauth_redirect_uris: str = ""

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # Agent defaults
    default_vm_size: str = "e2-small"
    default_agent_platform: str = "openclaw"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
