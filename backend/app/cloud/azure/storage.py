"""Azure Blob Storage provider implementation."""

import json
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
from azure.core.exceptions import ResourceNotFoundError

from app.cloud.interfaces import (
    StorageProvider,
    ScopedCredentials,
    StorageObject,
)
from app.config import get_settings


class AzureBlobStorageProvider(StorageProvider):
    """Azure Blob Storage implementation of StorageProvider."""

    def __init__(self):
        settings = get_settings()
        self.storage_account = settings.azure_storage_account
        self.account_url = f"https://{self.storage_account}.blob.core.windows.net"

        # Initialize Azure client with DefaultAzureCredential
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

    async def create_bucket(self, name: str, user_id: str) -> str:
        """Create a new Azure Blob container."""
        container_name = self._get_container_name(name, user_id)

        container_client = self.client.get_container_client(container_name)

        # Create the container with metadata
        container_client.create_container(
            metadata={
                "zerg_rush": "agent-bucket",
                "user_id": user_id.replace("-", ""),
            }
        )

        return container_name

    async def delete_bucket(self, bucket_id: str) -> None:
        """Delete an Azure Blob container and all its contents."""
        container_client = self.client.get_container_client(bucket_id)

        # Delete all blobs first
        blobs = container_client.list_blobs()
        for blob in blobs:
            container_client.delete_blob(blob.name)

        # Delete the container
        container_client.delete_container()

    async def create_scoped_credentials(
        self, bucket_id: str, permissions: list[str] | None = None
    ) -> ScopedCredentials:
        """Create credentials scoped to a specific container.

        This creates a SAS token with limited permissions.
        """
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

        return ScopedCredentials(
            credentials_json=creds_json,
            expires_at=expiry,
        )

    async def list_objects(
        self, bucket_id: str, prefix: str = ""
    ) -> list[StorageObject]:
        """List objects in an Azure Blob container."""
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

    async def upload_object(self, bucket_id: str, key: str, data: bytes) -> None:
        """Upload an object to an Azure Blob container."""
        container_client = self.client.get_container_client(bucket_id)
        blob_client = container_client.get_blob_client(key)
        blob_client.upload_blob(data, overwrite=True)

    async def download_object(self, bucket_id: str, key: str) -> bytes:
        """Download an object from an Azure Blob container."""
        container_client = self.client.get_container_client(bucket_id)
        blob_client = container_client.get_blob_client(key)
        download_stream = blob_client.download_blob()
        return download_stream.readall()

    async def delete_object(self, bucket_id: str, key: str) -> None:
        """Delete an object from an Azure Blob container."""
        container_client = self.client.get_container_client(bucket_id)
        blob_client = container_client.get_blob_client(key)
        blob_client.delete_blob()

    async def get_signed_url(
        self, bucket_id: str, key: str, expires_in: int = 3600
    ) -> str:
        """Get a signed URL for an object."""
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

        return f"{self.account_url}/{bucket_id}/{key}?{sas_token}"
