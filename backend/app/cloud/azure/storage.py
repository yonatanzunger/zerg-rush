"""Azure Blob Storage provider implementation."""

import json
import time
from datetime import datetime, timedelta, timezone
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobServiceClient,
    ContainerClient,
    generate_container_sas,
    generate_blob_sas,
    ContainerSasPermissions,
    BlobSasPermissions,
)
from azure.core.credentials import AccessToken
from azure.core.exceptions import ResourceNotFoundError

from app.cloud.interfaces import (
    StorageProvider,
    ScopedCredentials,
    StorageObject,
    UserCredentials,
)
from app.config import get_settings
from app.tracing import Session


class StaticTokenCredential:
    """Simple credential wrapper for Azure SDK using a static access token."""

    def __init__(self, access_token: str):
        self._token = access_token

    def get_token(self, *scopes, **kwargs) -> AccessToken:
        # Return the token with a 1-hour expiry (token is already valid)
        return AccessToken(self._token, int(time.time()) + 3600)


class AzureBlobStorageProvider(StorageProvider):
    """Azure Blob Storage implementation of StorageProvider."""

    def __init__(self, user_credentials: UserCredentials | None = None):
        """Initialize the Azure Blob Storage provider.

        Args:
            user_credentials: Optional user OAuth credentials. If provided,
                these will be used instead of DefaultAzureCredential.
        """
        settings = get_settings()
        self.storage_account = settings.azure_storage_account
        self.account_url = f"https://{self.storage_account}.blob.core.windows.net"

        if user_credentials:
            # Use user OAuth credentials
            self.credential = StaticTokenCredential(user_credentials.access_token)
        else:
            # Fall back to DefaultAzureCredential (for system operations)
            self.credential = DefaultAzureCredential()

        self.client = BlobServiceClient(
            account_url=self.account_url,
            credential=self.credential,
        )

    def _get_container_name(self, name: str, user_id: str) -> str:
        """Generate a unique container name.

        Azure container names must be lowercase, 3-63 characters,
        contain only letters, numbers, and hyphens.
        """
        clean_user_id = user_id.replace("-", "")[:8].lower()
        clean_name = name.lower().replace("_", "-")[:20]
        container_name = f"zr-{clean_user_id}-{clean_name}"
        # Ensure minimum length
        if len(container_name) < 3:
            container_name = f"zr-{container_name}"
        return container_name[:63]

    async def create_bucket(
        self, name: str, user_id: str, session: Session | None = None
    ) -> str:
        """Create a new Azure Blob container."""
        container_name = self._get_container_name(name, user_id)

        if session:
            session.log("Creating Azure Blob container", name=name, container_name=container_name)

        try:
            container_client = self.client.get_container_client(container_name)

            # Create the container with metadata
            container_client.create_container(
                metadata={
                    "zerg_rush": "agent-bucket",
                    "user_id": user_id.replace("-", ""),
                }
            )

            if session:
                session.log("Azure Blob container created", container_name=container_name)

            return container_name
        except Exception as e:
            if session:
                session.log(
                    "Azure Blob container creation failed",
                    container_name=container_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def delete_bucket(
        self, bucket_id: str, session: Session | None = None
    ) -> None:
        """Delete an Azure Blob container and all its contents."""
        if session:
            session.log("Deleting Azure Blob container", bucket_id=bucket_id)

        try:
            container_client = self.client.get_container_client(bucket_id)

            # Delete all blobs first
            blobs = container_client.list_blobs()
            for blob in blobs:
                container_client.delete_blob(blob.name)

            # Delete the container
            container_client.delete_container()

            if session:
                session.log("Azure Blob container deleted", bucket_id=bucket_id)
        except Exception as e:
            if session:
                session.log(
                    "Azure Blob container deletion failed",
                    bucket_id=bucket_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def create_scoped_credentials(
        self,
        bucket_id: str,
        permissions: list[str] | None = None,
        session: Session | None = None,
    ) -> ScopedCredentials:
        """Create credentials scoped to a specific container.

        This creates a SAS token with limited permissions.
        """
        if session:
            session.log("Creating scoped credentials", bucket_id=bucket_id)

        try:
            # Default permissions: read/write to the container
            if permissions is None:
                sas_permissions = ContainerSasPermissions(
                    read=True, write=True, delete=True, list=True
                )
            else:
                # Parse permissions
                sas_permissions = ContainerSasPermissions(
                    read="read" in permissions,
                    write="write" in permissions,
                    delete="delete" in permissions,
                    list="list" in permissions,
                )

            # Get the account key for SAS generation
            # In production, use User Delegation SAS with AAD credentials
            expiry = datetime.now(timezone.utc) + timedelta(hours=1)

            # Generate a User Delegation Key (requires AAD authentication)
            delegation_key = self.client.get_user_delegation_key(
                key_start_time=datetime.now(timezone.utc),
                key_expiry_time=expiry,
            )

            # Generate SAS token
            sas_token = generate_container_sas(
                account_name=self.storage_account,
                container_name=bucket_id,
                user_delegation_key=delegation_key,
                permission=sas_permissions,
                expiry=expiry,
            )

            # Return credentials as JSON that can be used by the agent
            creds_json = json.dumps(
                {
                    "type": "azure_sas",
                    "account_url": self.account_url,
                    "container": bucket_id,
                    "sas_token": sas_token,
                }
            )

            if session:
                session.log("Scoped credentials created", bucket_id=bucket_id)

            return ScopedCredentials(
                credentials_json=creds_json,
                expires_at=expiry,
            )
        except Exception as e:
            if session:
                session.log(
                    "Scoped credentials creation failed",
                    bucket_id=bucket_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def list_objects(
        self, bucket_id: str, prefix: str = "", session: Session | None = None
    ) -> list[StorageObject]:
        """List objects in an Azure Blob container."""
        try:
            container_client = self.client.get_container_client(bucket_id)

            objects = []
            blobs = container_client.list_blobs(name_starts_with=prefix)

            for blob in blobs:
                objects.append(
                    StorageObject(
                        key=blob.name,
                        size=blob.size or 0,
                        last_modified=blob.last_modified or datetime.now(timezone.utc),
                        content_type=blob.content_settings.content_type
                        if blob.content_settings
                        else None,
                    )
                )

            return objects
        except Exception as e:
            if session:
                session.log(
                    "List objects failed",
                    bucket_id=bucket_id,
                    prefix=prefix,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def upload_object(
        self, bucket_id: str, key: str, data: bytes, session: Session | None = None
    ) -> None:
        """Upload an object to an Azure Blob container."""
        try:
            container_client = self.client.get_container_client(bucket_id)
            blob_client = container_client.get_blob_client(key)
            blob_client.upload_blob(data, overwrite=True)
            if session:
                session.log("Object uploaded", bucket_id=bucket_id, key=key, size=len(data))
        except Exception as e:
            if session:
                session.log(
                    "Object upload failed",
                    bucket_id=bucket_id,
                    key=key,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def download_object(
        self, bucket_id: str, key: str, session: Session | None = None
    ) -> bytes:
        """Download an object from an Azure Blob container."""
        try:
            container_client = self.client.get_container_client(bucket_id)
            blob_client = container_client.get_blob_client(key)
            download_stream = blob_client.download_blob()
            data = download_stream.readall()
            if session:
                session.log("Object downloaded", bucket_id=bucket_id, key=key, size=len(data))
            return data
        except Exception as e:
            if session:
                session.log(
                    "Object download failed",
                    bucket_id=bucket_id,
                    key=key,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def delete_object(
        self, bucket_id: str, key: str, session: Session | None = None
    ) -> None:
        """Delete an object from an Azure Blob container."""
        try:
            container_client = self.client.get_container_client(bucket_id)
            blob_client = container_client.get_blob_client(key)
            blob_client.delete_blob()
            if session:
                session.log("Object deleted", bucket_id=bucket_id, key=key)
        except Exception as e:
            if session:
                session.log(
                    "Object deletion failed",
                    bucket_id=bucket_id,
                    key=key,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def get_signed_url(
        self,
        bucket_id: str,
        key: str,
        expires_in: int = 3600,
        session: Session | None = None,
    ) -> str:
        """Get a signed URL for an object."""
        try:
            expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # Generate a User Delegation Key
            delegation_key = self.client.get_user_delegation_key(
                key_start_time=datetime.now(timezone.utc),
                key_expiry_time=expiry,
            )

            # Generate SAS token for the blob
            sas_token = generate_blob_sas(
                account_name=self.storage_account,
                container_name=bucket_id,
                blob_name=key,
                user_delegation_key=delegation_key,
                permission=BlobSasPermissions(read=True),
                expiry=expiry,
            )

            if session:
                session.log("Signed URL generated", bucket_id=bucket_id, key=key)

            return f"{self.account_url}/{bucket_id}/{key}?{sas_token}"
        except Exception as e:
            if session:
                session.log(
                    "Signed URL generation failed",
                    bucket_id=bucket_id,
                    key=key,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise
