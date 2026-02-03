"""Azure Key Vault provider implementation."""

import time
from datetime import datetime, timezone

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.core.credentials import AccessToken
from azure.core.exceptions import ResourceNotFoundError

from app.cloud.interfaces import (
    SecretProvider,
    SecretMetadata,
    UserCredentials,
)
from app.config import get_settings


class StaticTokenCredential:
    """Simple credential wrapper for Azure SDK using a static access token."""

    def __init__(self, access_token: str):
        self._token = access_token

    def get_token(self, *scopes, **kwargs) -> AccessToken:
        # Return the token with a 1-hour expiry (token is already valid)
        return AccessToken(self._token, int(time.time()) + 3600)


class AzureKeyVaultProvider(SecretProvider):
    """Azure Key Vault implementation of SecretProvider."""

    def __init__(self, user_credentials: UserCredentials | None = None):
        """Initialize the Azure Key Vault provider.

        Args:
            user_credentials: Optional user OAuth credentials. If provided,
                these will be used instead of DefaultAzureCredential.
        """
        settings = get_settings()
        self.vault_name = settings.azure_keyvault_name
        self.vault_url = f"https://{self.vault_name}.vault.azure.net"

        if user_credentials:
            # Use user OAuth credentials
            self.credential = StaticTokenCredential(user_credentials.access_token)
        else:
            # Fall back to DefaultAzureCredential (for system operations)
            self.credential = DefaultAzureCredential()

        self.client = SecretClient(
            vault_url=self.vault_url,
            credential=self.credential,
        )

    def _get_secret_name(self, user_id: str, name: str) -> str:
        """Generate a unique secret name.

        Azure Key Vault secret names must be 1-127 characters,
        containing only alphanumeric characters and hyphens.
        """
        clean_user_id = user_id.replace("-", "")[:8]
        clean_name = name.lower().replace(" ", "-").replace("_", "-")[:40]
        # Remove any non-alphanumeric/hyphen characters
        clean_name = "".join(c for c in clean_name if c.isalnum() or c == "-")
        return f"zr-{clean_user_id}-{clean_name}"

    def _parse_secret_ref(self, secret_ref: str) -> str:
        """Parse a secret reference to get the secret name.

        Secret refs can be either:
        - Full URL: https://vault.vault.azure.net/secrets/secret-name
        - Just the name: secret-name
        """
        if "/" in secret_ref:
            # Extract name from URL
            return secret_ref.rstrip("/").split("/")[-1]
        return secret_ref

    async def store_secret(self, user_id: str, name: str, value: str) -> str:
        """Store a secret in Azure Key Vault."""
        secret_name = self._get_secret_name(user_id, name)

        # Set the secret with tags for organization
        secret = self.client.set_secret(
            secret_name,
            value,
            tags={
                "zerg-rush": "credential",
                "user-id": user_id.replace("-", ""),
                "original-name": name[:256],  # Preserve original name
            },
        )

        return secret.id  # Returns full URL to the secret

    async def get_secret(self, secret_ref: str) -> str:
        """Retrieve a secret value from Azure Key Vault."""
        secret_name = self._parse_secret_ref(secret_ref)
        secret = self.client.get_secret(secret_name)
        return secret.value

    async def delete_secret(self, secret_ref: str) -> None:
        """Delete a secret from Azure Key Vault.

        Note: Azure Key Vault uses soft-delete by default.
        The secret will be recoverable for the retention period.
        """
        secret_name = self._parse_secret_ref(secret_ref)

        # Begin deletion
        poller = self.client.begin_delete_secret(secret_name)
        poller.result()

    async def list_secrets(self, user_id: str) -> list[SecretMetadata]:
        """List all secrets for a user."""
        secrets = []
        user_id_clean = user_id.replace("-", "")

        # List all secrets and filter by user tag
        for secret_properties in self.client.list_properties_of_secrets():
            # Check if this secret belongs to the user
            tags = secret_properties.tags or {}
            if tags.get("user-id") == user_id_clean:
                # Parse creation time
                created_at = secret_properties.created_on or datetime.now(timezone.utc)

                # Get the original name from tags or use the secret name
                original_name = tags.get("original-name", secret_properties.name)

                secrets.append(
                    SecretMetadata(
                        secret_id=secret_properties.id,
                        name=original_name,
                        created_at=created_at,
                        version=secret_properties.version,
                    )
                )

        return secrets

    async def update_secret(self, secret_ref: str, value: str) -> None:
        """Update a secret's value by setting a new version."""
        secret_name = self._parse_secret_ref(secret_ref)

        # Get existing secret to preserve tags
        try:
            existing = self.client.get_secret(secret_name)
            tags = existing.properties.tags
        except ResourceNotFoundError:
            tags = {}

        # Set new value (creates new version)
        self.client.set_secret(secret_name, value, tags=tags)
