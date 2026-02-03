"""Abstract interfaces for cloud providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class VMStatus(str, Enum):
    """VM status enumeration."""

    CREATING = "creating"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    STARTING = "starting"
    DELETING = "deleting"
    DELETED = "deleted"
    ERROR = "error"


@dataclass
class VMConfig:
    """Configuration for creating a VM."""

    name: str
    size: str  # e.g., "e2-small", "t3.small"
    image: str  # OS image
    user_id: str  # For tagging/organization
    agent_id: str  # For tagging/organization
    startup_script: str | None = None
    labels: dict[str, str] | None = None


@dataclass
class VMInstance:
    """Represents a created VM instance."""

    vm_id: str
    name: str
    status: VMStatus
    internal_ip: str | None
    external_ip: str | None
    created_at: datetime
    zone: str
    metadata: dict[str, Any] | None = None


@dataclass
class CommandResult:
    """Result of a command execution on a VM."""

    exit_code: int
    stdout: str
    stderr: str


@dataclass
class ScopedCredentials:
    """Scoped credentials for accessing a specific resource."""

    credentials_json: str  # JSON-encoded credentials
    expires_at: datetime | None = None


@dataclass
class StorageObject:
    """Represents an object in cloud storage."""

    key: str
    size: int
    last_modified: datetime
    content_type: str | None = None


@dataclass
class SecretMetadata:
    """Metadata about a stored secret."""

    secret_id: str
    name: str
    created_at: datetime
    version: str | None = None


@dataclass
class UserInfo:
    """User information from OAuth provider."""

    subject: str  # Provider's user ID
    email: str
    name: str
    picture: str | None = None


@dataclass
class TokenResponse:
    """OAuth token response."""

    access_token: str
    refresh_token: str | None
    expires_in: int
    token_type: str = "Bearer"


@dataclass
class UserCredentials:
    """User OAuth credentials for cloud operations.

    These credentials are used to authenticate cloud API calls on behalf
    of the user, rather than using application default credentials.
    """

    access_token: str
    # GCP-specific
    project_id: str | None = None
    # Azure-specific
    subscription_id: str | None = None
    tenant_id: str | None = None
    resource_group: str | None = None


class VMProvider(ABC):
    """Abstract interface for VM management."""

    @abstractmethod
    async def create_vm(self, config: VMConfig) -> VMInstance:
        """Create a new VM instance."""
        ...

    @abstractmethod
    async def delete_vm(self, vm_id: str) -> None:
        """Delete a VM instance."""
        ...

    @abstractmethod
    async def start_vm(self, vm_id: str) -> None:
        """Start a stopped VM."""
        ...

    @abstractmethod
    async def stop_vm(self, vm_id: str) -> None:
        """Stop a running VM."""
        ...

    @abstractmethod
    async def get_vm_status(self, vm_id: str) -> VMInstance:
        """Get current status of a VM."""
        ...

    @abstractmethod
    async def run_command(
        self, vm_id: str, command: str, timeout: int = 300
    ) -> CommandResult:
        """Run a command on a VM."""
        ...

    @abstractmethod
    async def upload_file(
        self, vm_id: str, local_content: bytes, remote_path: str
    ) -> None:
        """Upload a file to a VM."""
        ...

    @abstractmethod
    async def download_file(self, vm_id: str, remote_path: str) -> bytes:
        """Download a file from a VM."""
        ...

    @abstractmethod
    async def list_files(self, vm_id: str, path: str) -> list[dict[str, Any]]:
        """List files in a directory on a VM."""
        ...


class StorageProvider(ABC):
    """Abstract interface for object storage management."""

    @abstractmethod
    async def create_bucket(self, name: str, user_id: str) -> str:
        """Create a new storage bucket. Returns bucket ID."""
        ...

    @abstractmethod
    async def delete_bucket(self, bucket_id: str) -> None:
        """Delete a storage bucket and all its contents."""
        ...

    @abstractmethod
    async def create_scoped_credentials(
        self, bucket_id: str, permissions: list[str] | None = None
    ) -> ScopedCredentials:
        """Create credentials scoped to a specific bucket."""
        ...

    @abstractmethod
    async def list_objects(
        self, bucket_id: str, prefix: str = ""
    ) -> list[StorageObject]:
        """List objects in a bucket."""
        ...

    @abstractmethod
    async def upload_object(self, bucket_id: str, key: str, data: bytes) -> None:
        """Upload an object to a bucket."""
        ...

    @abstractmethod
    async def download_object(self, bucket_id: str, key: str) -> bytes:
        """Download an object from a bucket."""
        ...

    @abstractmethod
    async def delete_object(self, bucket_id: str, key: str) -> None:
        """Delete an object from a bucket."""
        ...

    @abstractmethod
    async def get_signed_url(
        self, bucket_id: str, key: str, expires_in: int = 3600
    ) -> str:
        """Get a signed URL for an object."""
        ...


class SecretProvider(ABC):
    """Abstract interface for secret/credential storage."""

    @abstractmethod
    async def store_secret(self, user_id: str, name: str, value: str) -> str:
        """Store a secret. Returns secret reference ID."""
        ...

    @abstractmethod
    async def get_secret(self, secret_ref: str) -> str:
        """Retrieve a secret value by reference."""
        ...

    @abstractmethod
    async def delete_secret(self, secret_ref: str) -> None:
        """Delete a secret."""
        ...

    @abstractmethod
    async def list_secrets(self, user_id: str) -> list[SecretMetadata]:
        """List all secrets for a user."""
        ...

    @abstractmethod
    async def update_secret(self, secret_ref: str, value: str) -> None:
        """Update a secret's value."""
        ...


class IdentityProvider(ABC):
    """Abstract interface for OAuth authentication."""

    @abstractmethod
    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Get the OAuth authorization URL."""
        ...

    @abstractmethod
    async def exchange_code(
        self, code: str, redirect_uri: str
    ) -> TokenResponse:
        """Exchange authorization code for tokens."""
        ...

    @abstractmethod
    async def verify_token(self, token: str) -> UserInfo:
        """Verify an access token and return user info."""
        ...

    @abstractmethod
    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh an access token."""
        ...
