"""GCP Cloud Storage provider implementation."""

import json
from datetime import datetime, timedelta, timezone

from google.cloud import storage
from google.cloud import iam_credentials_v1
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as OAuthCredentials

from app.cloud.interfaces import (
    StorageProvider,
    ScopedCredentials,
    StorageObject,
    UserCredentials,
)
from app.config import get_settings
from app.tracing import Session, FunctionTrace


class GCPStorageProvider(StorageProvider):
    """GCP Cloud Storage implementation of StorageProvider."""

    def __init__(self, user_credentials: UserCredentials | None = None):
        """Initialize the GCP Storage provider.

        Args:
            user_credentials: Optional user OAuth credentials. If provided,
                these will be used instead of application default credentials.
        """
        settings = get_settings()
        self.location = settings.gcp_region

        if user_credentials:
            # Use user OAuth credentials
            credentials = OAuthCredentials(token=user_credentials.access_token)
            self.project_id = user_credentials.project_id or settings.gcp_project_id
            self.client = storage.Client(
                project=self.project_id,
                credentials=credentials,
            )
        else:
            # Fall back to application default credentials (for system operations)
            self.project_id = settings.gcp_project_id
            self.client = storage.Client(project=self.project_id)

    def _get_bucket_name(self, name: str, user_id: str) -> str:
        """Generate a unique bucket name."""
        # Bucket names must be globally unique and follow naming rules
        # Use project ID as prefix to help ensure uniqueness
        clean_user_id = user_id.replace("-", "")[:8]
        clean_name = name.lower().replace("_", "-")[:20]
        return f"{self.project_id}-zr-{clean_user_id}-{clean_name}"

    async def create_bucket(
        self, name: str, user_id: str, session: Session | None = None
    ) -> str:
        """Create a new GCS bucket."""
        bucket_name = self._get_bucket_name(name, user_id)

        with FunctionTrace(
            session, "Creating GCS bucket", name=name, bucket_name=bucket_name
        ) as trace:
            bucket = self.client.bucket(bucket_name)
            bucket.storage_class = "STANDARD"

            # Set labels for organization
            bucket.labels = {
                "zerg-rush": "agent-bucket",
                "user-id": user_id.replace("-", ""),
            }

            # Create the bucket
            new_bucket = self.client.create_bucket(
                bucket,
                location=self.location,
            )

            # Set lifecycle rules (e.g., delete old versions after 30 days)
            new_bucket.add_lifecycle_delete_rule(
                age=30,
                is_live=False,  # Only non-current versions
            )
            new_bucket.patch()

            trace.log("GCS bucket created", bucket_name=bucket_name)

            return bucket_name

    async def delete_bucket(
        self, bucket_id: str, session: Session | None = None
    ) -> None:
        """Delete a GCS bucket and all its contents."""
        with FunctionTrace(session, "Deleting GCS bucket", bucket_id=bucket_id) as trace:
            bucket = self.client.bucket(bucket_id)

            # Delete all objects first
            blobs = bucket.list_blobs()
            for blob in blobs:
                blob.delete()

            # Delete the bucket
            bucket.delete()

            trace.log("GCS bucket deleted", bucket_id=bucket_id)

    async def create_scoped_credentials(
        self,
        bucket_id: str,
        permissions: list[str] | None = None,
        session: Session | None = None,
    ) -> ScopedCredentials:
        """Create credentials scoped to a specific bucket.

        This creates a short-lived access token with limited permissions.
        In production, you'd typically create a service account with
        bucket-specific IAM bindings.
        """
        # Default permissions: read/write to the bucket
        if permissions is None:
            permissions = [
                "https://www.googleapis.com/auth/devstorage.read_write"
            ]

        # Use IAM Credentials API to generate access token
        # This requires the calling service account to have
        # roles/iam.serviceAccountTokenCreator
        iam_client = iam_credentials_v1.IAMCredentialsClient()

        # Generate a short-lived access token
        # Note: In production, you'd create a dedicated service account
        # per agent/bucket with specific IAM bindings
        response = iam_client.generate_access_token(
            name=f"projects/-/serviceAccounts/{self.project_id}@appspot.gserviceaccount.com",
            scope=permissions,
            lifetime={"seconds": 3600},  # 1 hour
        )

        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Return credentials as JSON that can be used by the agent
        creds_json = json.dumps({
            "type": "authorized_user",
            "access_token": response.access_token,
            "bucket": bucket_id,
        })

        return ScopedCredentials(
            credentials_json=creds_json,
            expires_at=expires_at,
        )

    async def list_objects(
        self, bucket_id: str, prefix: str = "", session: Session | None = None
    ) -> list[StorageObject]:
        """List objects in a GCS bucket."""
        bucket = self.client.bucket(bucket_id)
        blobs = bucket.list_blobs(prefix=prefix)

        objects = []
        for blob in blobs:
            objects.append(
                StorageObject(
                    key=blob.name,
                    size=blob.size or 0,
                    last_modified=blob.updated or datetime.now(timezone.utc),
                    content_type=blob.content_type,
                )
            )

        return objects

    async def upload_object(
        self, bucket_id: str, key: str, data: bytes, session: Session | None = None
    ) -> None:
        """Upload an object to a GCS bucket."""
        bucket = self.client.bucket(bucket_id)
        blob = bucket.blob(key)
        blob.upload_from_string(data)

    async def download_object(
        self, bucket_id: str, key: str, session: Session | None = None
    ) -> bytes:
        """Download an object from a GCS bucket."""
        bucket = self.client.bucket(bucket_id)
        blob = bucket.blob(key)
        return blob.download_as_bytes()

    async def delete_object(
        self, bucket_id: str, key: str, session: Session | None = None
    ) -> None:
        """Delete an object from a GCS bucket."""
        bucket = self.client.bucket(bucket_id)
        blob = bucket.blob(key)
        blob.delete()

    async def get_signed_url(
        self,
        bucket_id: str,
        key: str,
        expires_in: int = 3600,
        session: Session | None = None,
    ) -> str:
        """Get a signed URL for an object."""
        bucket = self.client.bucket(bucket_id)
        blob = bucket.blob(key)

        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expires_in),
            method="GET",
        )

        return url
