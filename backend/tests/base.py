"""Base test class and utilities for unittest-based async tests."""

import asyncio
import unittest
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cloud.interfaces import (
    VMProvider,
    StorageProvider,
    SecretProvider,
    IdentityProvider,
    VMConfig,
    VMInstance,
    VMStatus,
    ScopedCredentials,
    StorageObject,
    SecretMetadata,
    UserInfo,
    TokenResponse,
)
from app.models import Base, User
from app.db.session import get_db


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


class MockVMProvider(VMProvider):
    """Mock VM provider for testing."""

    def __init__(self):
        self.vms: dict[str, VMInstance] = {}

    async def create_vm(self, config: VMConfig) -> VMInstance:
        vm_id = f"vm-{uuid4().hex[:8]}"
        instance = VMInstance(
            vm_id=vm_id,
            name=config.name,
            status=VMStatus.RUNNING,
            internal_ip="http://10.0.0.1:8080",
            external_ip=None,
            created_at=datetime.now(timezone.utc),
            zone="us-central1-a",
        )
        self.vms[vm_id] = instance
        return instance

    async def delete_vm(self, vm_id: str) -> None:
        if vm_id in self.vms:
            del self.vms[vm_id]

    async def start_vm(self, vm_id: str) -> None:
        if vm_id in self.vms:
            self.vms[vm_id].status = VMStatus.RUNNING

    async def stop_vm(self, vm_id: str) -> None:
        if vm_id in self.vms:
            self.vms[vm_id].status = VMStatus.STOPPED

    async def get_vm_status(self, vm_id: str) -> VMInstance:
        if vm_id in self.vms:
            return self.vms[vm_id]
        return VMInstance(
            vm_id=vm_id,
            name="unknown",
            status=VMStatus.DELETED,
            internal_ip=None,
            external_ip=None,
            created_at=datetime.now(timezone.utc),
            zone="us-central1-a",
        )

    async def run_command(self, vm_id: str, command: str, timeout: int = 300):
        raise NotImplementedError()

    async def upload_file(self, vm_id: str, local_content: bytes, remote_path: str) -> None:
        raise NotImplementedError()

    async def download_file(self, vm_id: str, remote_path: str) -> bytes:
        raise NotImplementedError()

    async def list_files(self, vm_id: str, path: str) -> list[dict[str, Any]]:
        raise NotImplementedError()


class MockStorageProvider(StorageProvider):
    """Mock storage provider for testing."""

    def __init__(self):
        self.buckets: dict[str, dict[str, bytes]] = {}

    async def create_bucket(self, name: str, user_id: str) -> str:
        bucket_id = f"bucket-{uuid4().hex[:8]}"
        self.buckets[bucket_id] = {}
        return bucket_id

    async def delete_bucket(self, bucket_id: str) -> None:
        if bucket_id in self.buckets:
            del self.buckets[bucket_id]

    async def create_scoped_credentials(
        self, bucket_id: str, permissions: list[str] | None = None
    ) -> ScopedCredentials:
        return ScopedCredentials(
            credentials_json='{"type": "mock", "token": "test-token"}',
            expires_at=datetime.now(timezone.utc),
        )

    async def list_objects(self, bucket_id: str, prefix: str = "") -> list[StorageObject]:
        if bucket_id not in self.buckets:
            return []
        return [
            StorageObject(
                key=k,
                size=len(v),
                last_modified=datetime.now(timezone.utc),
            )
            for k, v in self.buckets[bucket_id].items()
            if k.startswith(prefix)
        ]

    async def upload_object(self, bucket_id: str, key: str, data: bytes) -> None:
        if bucket_id in self.buckets:
            self.buckets[bucket_id][key] = data

    async def download_object(self, bucket_id: str, key: str) -> bytes:
        if bucket_id in self.buckets and key in self.buckets[bucket_id]:
            return self.buckets[bucket_id][key]
        raise FileNotFoundError(f"Object {key} not found")

    async def delete_object(self, bucket_id: str, key: str) -> None:
        if bucket_id in self.buckets and key in self.buckets[bucket_id]:
            del self.buckets[bucket_id][key]

    async def get_signed_url(self, bucket_id: str, key: str, expires_in: int = 3600) -> str:
        return f"https://storage.example.com/{bucket_id}/{key}?token=signed"


class MockSecretProvider(SecretProvider):
    """Mock secret provider for testing."""

    def __init__(self):
        self.secrets: dict[str, str] = {}
        self.metadata: dict[str, SecretMetadata] = {}

    async def store_secret(self, user_id: str, name: str, value: str) -> str:
        secret_id = f"secret-{uuid4().hex[:8]}"
        self.secrets[secret_id] = value
        self.metadata[secret_id] = SecretMetadata(
            secret_id=secret_id,
            name=name,
            created_at=datetime.now(timezone.utc),
        )
        return secret_id

    async def get_secret(self, secret_ref: str) -> str:
        if secret_ref in self.secrets:
            return self.secrets[secret_ref]
        raise KeyError(f"Secret {secret_ref} not found")

    async def delete_secret(self, secret_ref: str) -> None:
        if secret_ref in self.secrets:
            del self.secrets[secret_ref]
        if secret_ref in self.metadata:
            del self.metadata[secret_ref]

    async def list_secrets(self, user_id: str) -> list[SecretMetadata]:
        return list(self.metadata.values())

    async def update_secret(self, secret_ref: str, value: str) -> None:
        if secret_ref in self.secrets:
            self.secrets[secret_ref] = value


class MockIdentityProvider(IdentityProvider):
    """Mock identity provider for testing."""

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        return f"https://auth.example.com/authorize?redirect_uri={redirect_uri}&state={state}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        return TokenResponse(
            access_token="mock-access-token",
            refresh_token="mock-refresh-token",
            expires_in=3600,
        )

    async def verify_token(self, token: str) -> UserInfo:
        return UserInfo(
            subject="google-123456",
            email="test@example.com",
            name="Test User",
            picture=None,
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        return TokenResponse(
            access_token="mock-new-access-token",
            refresh_token="mock-new-refresh-token",
            expires_in=3600,
        )


class AsyncTestCase(unittest.IsolatedAsyncioTestCase):
    """Base test case with database and HTTP client setup."""

    engine = None
    mock_providers: dict = None
    app: FastAPI = None
    client: AsyncClient = None
    auth_client: AsyncClient = None
    session: AsyncSession = None
    test_user: User = None
    _original_providers = None
    _mock_cloud_providers = None

    async def asyncSetUp(self):
        """Set up test fixtures."""
        # Create test engine
        self.engine = create_async_engine(TEST_DATABASE_URL, echo=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Create mock providers
        self.mock_providers = {
            "vm": MockVMProvider(),
            "storage": MockStorageProvider(),
            "secret": MockSecretProvider(),
            "identity": MockIdentityProvider(),
        }

        # Create session
        async_session_maker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self.session = async_session_maker()

        # Create test user
        self.test_user = User(
            id=str(uuid4()),
            email="test@example.com",
            name="Test User",
            oauth_provider="google",
            oauth_subject="google-123456",
            last_login=datetime.now(timezone.utc),
        )
        self.session.add(self.test_user)
        await self.session.commit()
        await self.session.refresh(self.test_user)

        # Set up app with overrides
        from app.main import app as main_app
        from app.cloud.factory import CloudProviders
        import app.cloud.factory as factory_module

        self.app = main_app

        # Override database dependency
        async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
            async_session = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with async_session() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        # Override cloud providers by setting the singleton directly
        self._mock_cloud_providers = CloudProviders(
            vm=self.mock_providers["vm"],
            storage=self.mock_providers["storage"],
            secret=self.mock_providers["secret"],
            identity=self.mock_providers["identity"],
        )

        self.app.dependency_overrides[get_db] = override_get_db
        self._original_providers = factory_module._providers
        factory_module._providers = self._mock_cloud_providers

        # Create clients
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://test",
        )

        from app.api.routes.auth import create_access_token
        token = create_access_token(self.test_user.id)

        self.auth_client = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def asyncTearDown(self):
        """Clean up test fixtures."""
        import app.cloud.factory as factory_module

        # Close clients
        if self.client:
            await self.client.aclose()
        if self.auth_client:
            await self.auth_client.aclose()

        # Close session
        if self.session:
            await self.session.close()

        # Drop tables and dispose engine
        if self.engine:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await self.engine.dispose()

        # Restore original providers
        if self.app:
            self.app.dependency_overrides.clear()
        factory_module._providers = self._original_providers
