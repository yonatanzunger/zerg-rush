"""GCP Secret Manager provider implementation."""

from datetime import datetime, timezone

from google.cloud import secretmanager
from google.oauth2.credentials import Credentials as OAuthCredentials

from app.cloud.interfaces import (
    SecretProvider,
    SecretMetadata,
    UserCredentials,
)
from app.config import get_settings
from app.tracing import Session


class GCPSecretProvider(SecretProvider):
    """GCP Secret Manager implementation of SecretProvider."""

    def __init__(self, user_credentials: UserCredentials | None = None):
        """Initialize the GCP Secret Manager provider.

        Args:
            user_credentials: Optional user OAuth credentials. If provided,
                these will be used instead of application default credentials.
        """
        settings = get_settings()

        if user_credentials:
            # Use user OAuth credentials
            credentials = OAuthCredentials(token=user_credentials.access_token)
            self.project_id = user_credentials.project_id or settings.gcp_project_id
            self.client = secretmanager.SecretManagerServiceClient(
                credentials=credentials
            )
        else:
            # Fall back to application default credentials (for system operations)
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

    async def store_secret(
        self, user_id: str, name: str, value: str, session: Session | None = None
    ) -> str:
        """Store a secret in GCP Secret Manager."""
        secret_id = self._get_secret_id(user_id, name)
        parent = f"projects/{self.project_id}"

        if session:
            session.log("Storing secret", name=name, secret_id=secret_id)

        try:
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

            if session:
                session.log("Secret stored", secret_id=secret_id)

            return created_secret.name
        except Exception as e:
            if session:
                session.log(
                    "Secret storage failed",
                    secret_id=secret_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def get_secret(
        self, secret_ref: str, session: Session | None = None
    ) -> str:
        """Retrieve a secret value from GCP Secret Manager."""
        # Access the latest version
        name = f"{secret_ref}/versions/latest"

        try:
            response = self.client.access_secret_version(name=name)
            if session:
                session.log("Secret retrieved", secret_ref=secret_ref)
            return response.payload.data.decode("utf-8")
        except Exception as e:
            if session:
                session.log(
                    "Secret retrieval failed",
                    secret_ref=secret_ref,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def delete_secret(
        self, secret_ref: str, session: Session | None = None
    ) -> None:
        """Delete a secret from GCP Secret Manager."""
        if session:
            session.log("Deleting secret", secret_ref=secret_ref)

        try:
            self.client.delete_secret(name=secret_ref)
            if session:
                session.log("Secret deleted", secret_ref=secret_ref)
        except Exception as e:
            if session:
                session.log(
                    "Secret deletion failed",
                    secret_ref=secret_ref,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def list_secrets(
        self, user_id: str, session: Session | None = None
    ) -> list[SecretMetadata]:
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

    async def update_secret(
        self, secret_ref: str, value: str, session: Session | None = None
    ) -> None:
        """Update a secret's value by adding a new version."""
        self.client.add_secret_version(
            request={
                "parent": secret_ref,
                "payload": {"data": value.encode("utf-8")},
            }
        )
