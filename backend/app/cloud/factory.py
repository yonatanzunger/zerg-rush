"""Factory for creating cloud provider instances."""

from typing import NamedTuple

from app.cloud.interfaces import (
    VMProvider,
    StorageProvider,
    SecretProvider,
    IdentityProvider,
    UserCredentials,
)
from app.config import get_settings


class CloudProviders(NamedTuple):
    """Container for all cloud provider instances."""

    vm: VMProvider
    storage: StorageProvider
    secret: SecretProvider
    identity: IdentityProvider


def get_cloud_providers(
    user_credentials: UserCredentials | None = None,
) -> CloudProviders:
    """Get cloud provider instances based on configuration.

    Args:
        user_credentials: Optional user OAuth credentials. If provided,
            providers will use these credentials for cloud operations.
            If None, providers fall back to application default credentials.

    Returns:
        CloudProviders tuple with VM, storage, secret, and identity providers.
    """
    settings = get_settings()

    if settings.cloud_provider == "gcp":
        from app.cloud.gcp import (
            GCPVMProvider,
            GCPCloudRunProvider,
            GCPStorageProvider,
            GCPSecretProvider,
            GoogleIdentityProvider,
        )

        # Choose compute provider based on gcp_compute_type setting
        if settings.gcp_compute_type == "cloudrun":
            compute_provider = GCPCloudRunProvider(user_credentials)
        else:
            compute_provider = GCPVMProvider(user_credentials)

        return CloudProviders(
            vm=compute_provider,
            storage=GCPStorageProvider(user_credentials),
            secret=GCPSecretProvider(user_credentials),
            identity=GoogleIdentityProvider(),  # Identity doesn't need user creds
        )
    elif settings.cloud_provider == "aws":
        raise NotImplementedError("AWS provider not yet implemented")
    elif settings.cloud_provider == "azure":
        from app.cloud.azure import (
            AzureACIProvider,
            AzureBlobStorageProvider,
            AzureKeyVaultProvider,
            AzureADIdentityProvider,
        )

        # Choose compute provider based on azure_compute_type setting
        if settings.azure_compute_type == "aci":
            compute_provider = AzureACIProvider(user_credentials)
        else:
            raise NotImplementedError(
                "Azure VM provider not yet implemented. Use azure_compute_type=aci"
            )

        return CloudProviders(
            vm=compute_provider,
            storage=AzureBlobStorageProvider(user_credentials),
            secret=AzureKeyVaultProvider(user_credentials),
            identity=AzureADIdentityProvider(),  # Identity doesn't need user creds
        )
    else:
        raise ValueError(f"Unknown cloud provider: {settings.cloud_provider}")


# Singleton instance for identity provider operations (login flow)
# This uses ADC since it's not user-specific
_identity_providers: CloudProviders | None = None


def get_providers() -> CloudProviders:
    """Get cloud providers with application default credentials.

    This is used for:
    - OAuth login flow (identity provider)
    - System operations that don't require user credentials

    For user-specific cloud operations, use get_cloud_providers(user_credentials)
    via the dependency injection system.
    """
    global _identity_providers
    if _identity_providers is None:
        _identity_providers = get_cloud_providers(user_credentials=None)
    return _identity_providers
