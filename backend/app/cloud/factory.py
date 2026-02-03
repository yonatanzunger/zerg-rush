"""Factory for creating cloud provider instances."""

from typing import NamedTuple

from app.cloud.interfaces import (
    VMProvider,
    StorageProvider,
    SecretProvider,
    IdentityProvider,
)
from app.config import get_settings


class CloudProviders(NamedTuple):
    """Container for all cloud provider instances."""

    vm: VMProvider
    storage: StorageProvider
    secret: SecretProvider
    identity: IdentityProvider


def get_cloud_providers() -> CloudProviders:
    """Get cloud provider instances based on configuration."""
    settings = get_settings()

    if settings.cloud_provider == "gcp":
        from app.cloud.gcp import (
            GCPVMProvider,
            GCPCloudRunProvider,
            GCPStorageProvider,
            GCPSecretProvider,
            GoogleIdentityProvider,
        )

        # Choose compute provider based on compute_type setting
        if settings.compute_type == "cloudrun":
            compute_provider = GCPCloudRunProvider()
        else:
            compute_provider = GCPVMProvider()

        return CloudProviders(
            vm=compute_provider,
            storage=GCPStorageProvider(),
            secret=GCPSecretProvider(),
            identity=GoogleIdentityProvider(),
        )
    elif settings.cloud_provider == "aws":
        raise NotImplementedError("AWS provider not yet implemented")
    elif settings.cloud_provider == "azure":
        raise NotImplementedError("Azure provider not yet implemented")
    else:
        raise ValueError(f"Unknown cloud provider: {settings.cloud_provider}")


# Singleton instance (lazy initialization)
_providers: CloudProviders | None = None


def get_providers() -> CloudProviders:
    """Get the singleton cloud providers instance."""
    global _providers
    if _providers is None:
        _providers = get_cloud_providers()
    return _providers
