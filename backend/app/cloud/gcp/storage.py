"""GCP Cloud Storage provider implementation."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from google.auth import iam
from google.auth.transport import requests as google_requests
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


def _credentials_can_sign(credentials) -> bool:
    """Check if credentials have signing capability (private key)."""
    # Service account credentials have a signer attribute
    if hasattr(credentials, "signer") and credentials.signer is not None:
        return True
    # Some credentials have sign_bytes method directly
    if hasattr(credentials, "sign_bytes") and callable(credentials.sign_bytes):
        return True
    return False


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
        self._using_user_credentials = False
        self._service_account_email = settings.gcp_service_account_email
        self._can_sign_directly = False
        self._adc_credentials = None

        if user_credentials:
            # Use user OAuth credentials (cannot sign directly)
            credentials = OAuthCredentials(token=user_credentials.access_token)
            self.project_id = user_credentials.project_id or settings.gcp_project_id
            self.client = storage.Client(
                project=self.project_id,
                credentials=credentials,
            )
            self._using_user_credentials = True
            self._user_credentials = credentials
        else:
            # Fall back to application default credentials (for system operations)
            self.project_id = settings.gcp_project_id
            self.client = storage.Client(project=self.project_id)
            self._user_credentials = None

            # Check if ADC can sign directly (e.g., service account key file)
            # Store ADC for potential signing use
            self._adc_credentials = self.client._credentials
            self._can_sign_directly = _credentials_can_sign(self._adc_credentials)

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
            trace.log("Configuring bucket settings...")
            bucket = self.client.bucket(bucket_name)
            bucket.storage_class = "STANDARD"

            # Set labels for organization
            bucket.labels = {
                "zerg-rush": "agent-bucket",
                "user-id": user_id.replace("-", ""),
            }

            # Create the bucket (run in thread pool to avoid blocking event loop)
            trace.log("Sending create request to GCS...", location=self.location)
            new_bucket = await asyncio.to_thread(
                self.client.create_bucket,
                bucket,
                location=self.location,
            )

            # Set lifecycle rules (e.g., delete old versions after 30 days)
            trace.log("Configuring lifecycle rules...")
            new_bucket.add_lifecycle_delete_rule(
                age=30,
                is_live=False,  # Only non-current versions
            )
            await asyncio.to_thread(new_bucket.patch)

            trace.log("GCS bucket created successfully", bucket_name=bucket_name)

            return bucket_name

    async def delete_bucket(
        self, bucket_id: str, session: Session | None = None
    ) -> None:
        """Delete a GCS bucket and all its contents."""
        with FunctionTrace(session, "Deleting GCS bucket", bucket_id=bucket_id) as trace:
            bucket = self.client.bucket(bucket_id)

            # Delete all objects first (run in thread pool)
            trace.log("Listing objects in bucket...")
            blobs = await asyncio.to_thread(lambda: list(bucket.list_blobs()))
            if blobs:
                trace.log(f"Deleting {len(blobs)} objects from bucket...")
                for blob in blobs:
                    await asyncio.to_thread(blob.delete)
            else:
                trace.log("Bucket is empty")

            # Delete the bucket
            trace.log("Deleting bucket...")
            await asyncio.to_thread(bucket.delete)

            trace.log("GCS bucket deleted successfully", bucket_id=bucket_id)

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

        # Generate a short-lived access token (run in thread pool)
        # Note: In production, you'd create a dedicated service account
        # per agent/bucket with specific IAM bindings
        response = await asyncio.to_thread(
            iam_client.generate_access_token,
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
        blobs = await asyncio.to_thread(lambda: list(bucket.list_blobs(prefix=prefix)))

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
        await asyncio.to_thread(blob.upload_from_string, data)

    async def download_object(
        self, bucket_id: str, key: str, session: Session | None = None
    ) -> bytes:
        """Download an object from a GCS bucket."""
        bucket = self.client.bucket(bucket_id)
        blob = bucket.blob(key)
        return await asyncio.to_thread(blob.download_as_bytes)

    async def delete_object(
        self, bucket_id: str, key: str, session: Session | None = None
    ) -> None:
        """Delete an object from a GCS bucket."""
        bucket = self.client.bucket(bucket_id)
        blob = bucket.blob(key)
        await asyncio.to_thread(blob.delete)

    async def get_signed_url(
        self,
        bucket_id: str,
        key: str,
        expires_in: int = 3600,
        session: Session | None = None,
    ) -> str:
        """Get a signed URL for an object.

        Signing strategy:
        1. If ADC has signing capability (service account key), sign directly
        2. If using user OAuth credentials or ADC without signing capability,
           use IAM Credentials API to sign on behalf of the configured service account

        For IAM signing, the caller must have iam.serviceAccounts.signBlob permission
        on the configured service account.
        """
        bucket = self.client.bucket(bucket_id)
        blob = bucket.blob(key)

        # Case 1: ADC can sign directly (service account with key file)
        if not self._using_user_credentials and self._can_sign_directly:
            url = await asyncio.to_thread(
                blob.generate_signed_url,
                version="v4",
                expiration=timedelta(seconds=expires_in),
                method="GET",
            )
            return url

        # Case 2 & 3: Need IAM signing (user credentials or ADC without signing)
        if not self._service_account_email:
            raise ValueError(
                "GCP_SERVICE_ACCOUNT_EMAIL must be configured to sign URLs "
                "when credentials don't have signing capability. "
                "Either run Zerg Rush with a service account key file, "
                "or configure a signing service account. See README.md for setup."
            )

        # Determine which credentials to use for calling IAM signBlob API
        if self._using_user_credentials:
            # Use user's OAuth token to call IAM API
            signing_caller_credentials = self._user_credentials
        else:
            # Use ADC to call IAM API (e.g., compute engine default service account)
            signing_caller_credentials = self._adc_credentials

        # Create an IAM signer that uses the signBlob API
        signer = iam.Signer(
            request=google_requests.Request(),
            credentials=signing_caller_credentials,
            service_account_email=self._service_account_email,
        )

        # Create signing credentials using the IAM signer
        signing_credentials = service_account.Credentials(
            signer=signer,
            service_account_email=self._service_account_email,
            token_uri="https://oauth2.googleapis.com/token",
            project_id=self.project_id,
        )

        url = await asyncio.to_thread(
            blob.generate_signed_url,
            version="v4",
            expiration=timedelta(seconds=expires_in),
            method="GET",
            credentials=signing_credentials,
        )

        return url
