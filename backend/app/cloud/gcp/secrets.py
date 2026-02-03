"""GCP Secret Manager provider implementation."""

from datetime import datetime, timezone

from google.cloud import secretmanager

from app.cloud.interfaces import (
    SecretProvider,
    SecretMetadata,
)
from app.config import get_settings


class GCPSecretProvider(SecretProvider):
    """GCP Secret Manager implementation of SecretProvider."""

    def __init__(self):
        settings = get_settings()
        self.project_id = settings.gcp_project_id
        self.client = secretmanager.SecretManagerServiceClient()

    def _get_secret_id(self, user_id: str, name: str) -> str:
        """Generate a unique secret ID."""
        clean_user_id = user_id.replace("-", "")[:8]
        clean_name = name.lower().replace(" ", "-").replace("_", "-")[:40]
        return f"zr-{clean_user_id}-{clean_name}"

    def _parse_secret_name(self, secret_ref: str) -> tuple[str, str]:
        """Parse a secret reference into project and secret ID."""
        # Expected format: projects/{project}/secrets/{secret_id}
        parts = secret_ref.split("/")
        if len(parts) >= 4:
            return parts[1], parts[3]
        # Assume it's just the secret ID
        return self.project_id, secret_ref

    async def store_secret(self, user_id: str, name: str, value: str) -> str:
        """Store a secret in GCP Secret Manager."""
        secret_id = self._get_secret_id(user_id, name)
        parent = f"projects/{self.project_id}"

        # Create the secret
        secret = {
            "replication": {"automatic": {}},
            "labels": {
                "zerg-rush": "credential",
                "user-id": user_id.replace("-", ""),
            },
        }

        try:
            created_secret = self.client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": secret,
                }
            )
        except Exception as e:
            if "ALREADY_EXISTS" in str(e):
                # Secret already exists, we'll add a new version
                created_secret = self.client.get_secret(
                    name=f"{parent}/secrets/{secret_id}"
                )
            else:
                raise

        # Add the secret version
        self.client.add_secret_version(
            request={
                "parent": created_secret.name,
                "payload": {"data": value.encode("utf-8")},
            }
        )

        return created_secret.name

    async def get_secret(self, secret_ref: str) -> str:
        """Retrieve a secret value from GCP Secret Manager."""
        # Access the latest version
        name = f"{secret_ref}/versions/latest"

        response = self.client.access_secret_version(name=name)
        return response.payload.data.decode("utf-8")

    async def delete_secret(self, secret_ref: str) -> None:
        """Delete a secret from GCP Secret Manager."""
        self.client.delete_secret(name=secret_ref)

    async def list_secrets(self, user_id: str) -> list[SecretMetadata]:
        """List all secrets for a user."""
        parent = f"projects/{self.project_id}"

        # Filter by user label
        filter_str = f'labels.user-id="{user_id.replace("-", "")}"'

        secrets = []
        for secret in self.client.list_secrets(parent=parent, filter=filter_str):
            # Parse creation time
            created_at = datetime.fromtimestamp(
                secret.create_time.seconds, tz=timezone.utc
            )

            # Extract name from the full resource name
            name = secret.name.split("/")[-1]

            secrets.append(
                SecretMetadata(
                    secret_id=secret.name,
                    name=name,
                    created_at=created_at,
                )
            )

        return secrets

    async def update_secret(self, secret_ref: str, value: str) -> None:
        """Update a secret's value by adding a new version."""
        self.client.add_secret_version(
            request={
                "parent": secret_ref,
                "payload": {"data": value.encode("utf-8")},
            }
        )
