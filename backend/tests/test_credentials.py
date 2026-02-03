"""Tests for credentials management routes."""

import unittest
from uuid import uuid4

from sqlalchemy import select

from app.models import Credential
from tests.base import AsyncTestCase


class TestListCredentials(AsyncTestCase):
    """Tests for listing credentials."""

    async def test_list_credentials_requires_auth(self):
        """Test that listing credentials requires authentication."""
        response = await self.client.get("/credentials")
        self.assertEqual(response.status_code, 403)

    async def test_list_credentials_empty(self):
        """Test listing credentials when user has none."""
        response = await self.auth_client.get("/credentials")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["credentials"], [])
        self.assertEqual(data["total"], 0)

    async def test_list_credentials_filter_by_type(self):
        """Test filtering credentials by type."""
        for cred_type in ["llm", "cloud", "utility"]:
            credential = Credential(
                id=str(uuid4()),
                user_id=self.test_user.id,
                name=f"{cred_type.upper()} Key",
                type=cred_type,
                secret_ref=f"secret-{cred_type}",
            )
            self.session.add(credential)
        await self.session.commit()

        response = await self.auth_client.get("/credentials?type=llm")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["credentials"][0]["type"], "llm")


class TestCreateCredential(AsyncTestCase):
    """Tests for creating credentials."""

    async def test_create_credential_requires_auth(self):
        """Test that creating credentials requires authentication."""
        response = await self.client.post(
            "/credentials",
            json={
                "name": "API Key",
                "type": "llm",
                "value": "sk-test123",
            },
        )
        self.assertEqual(response.status_code, 403)

    async def test_create_credential_success(self):
        """Test successful credential creation."""
        response = await self.auth_client.post(
            "/credentials",
            json={
                "name": "Anthropic API Key",
                "type": "llm",
                "description": "My Anthropic API key",
                "value": "sk-ant-test123",
            },
        )
        self.assertEqual(response.status_code, 201)

        data = response.json()
        self.assertEqual(data["name"], "Anthropic API Key")
        self.assertEqual(data["type"], "llm")
        self.assertEqual(data["description"], "My Anthropic API key")
        self.assertNotIn("value", data)
        self.assertNotIn("secret_ref", data)

    async def test_create_credential_invalid_type(self):
        """Test that invalid credential type is rejected."""
        response = await self.auth_client.post(
            "/credentials",
            json={
                "name": "Bad Key",
                "type": "invalid",
                "value": "test123",
            },
        )
        self.assertEqual(response.status_code, 422)

    async def test_create_credential_empty_name(self):
        """Test that empty name is rejected."""
        response = await self.auth_client.post(
            "/credentials",
            json={
                "name": "",
                "type": "llm",
                "value": "test123",
            },
        )
        self.assertEqual(response.status_code, 422)

    async def test_create_credential_empty_value(self):
        """Test that empty value is rejected."""
        response = await self.auth_client.post(
            "/credentials",
            json={
                "name": "Empty Value",
                "type": "llm",
                "value": "",
            },
        )
        self.assertEqual(response.status_code, 422)


class TestGetCredential(AsyncTestCase):
    """Tests for getting a single credential."""

    async def test_get_credential_not_found(self):
        """Test getting non-existent credential."""
        response = await self.auth_client.get("/credentials/nonexistent-id")
        self.assertEqual(response.status_code, 404)

    async def test_get_credential_success(self):
        """Test successful credential retrieval."""
        cred_id = str(uuid4())
        credential = Credential(
            id=cred_id,
            user_id=self.test_user.id,
            name="Test Key",
            type="cloud",
            description="A test key",
            secret_ref="secret-ref-123",
        )
        self.session.add(credential)
        await self.session.commit()

        response = await self.auth_client.get(f"/credentials/{cred_id}")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["id"], cred_id)
        self.assertEqual(data["name"], "Test Key")
        self.assertEqual(data["type"], "cloud")
        self.assertEqual(data["description"], "A test key")
        self.assertNotIn("secret_ref", data)

    async def test_get_credential_other_user(self):
        """Test that users cannot access other users' credentials."""
        cred_id = str(uuid4())
        other_user_id = str(uuid4())
        credential = Credential(
            id=cred_id,
            user_id=other_user_id,
            name="Other Key",
            type="llm",
            secret_ref="other-secret",
        )
        self.session.add(credential)
        await self.session.commit()

        response = await self.auth_client.get(f"/credentials/{cred_id}")
        self.assertEqual(response.status_code, 404)


class TestDeleteCredential(AsyncTestCase):
    """Tests for deleting credentials."""

    async def test_delete_credential_requires_auth(self):
        """Test that deleting credentials requires authentication."""
        response = await self.client.delete("/credentials/some-id")
        self.assertEqual(response.status_code, 403)

    async def test_delete_credential_not_found(self):
        """Test deleting non-existent credential."""
        response = await self.auth_client.delete("/credentials/nonexistent-id")
        self.assertEqual(response.status_code, 404)

    async def test_delete_credential_success(self):
        """Test successful credential deletion."""
        secret_ref = await self.mock_providers["secret"].store_secret(
            user_id=self.test_user.id,
            name="Delete Me",
            value="secret-value",
        )

        cred_id = str(uuid4())
        credential = Credential(
            id=cred_id,
            user_id=self.test_user.id,
            name="Delete Me",
            type="utility",
            secret_ref=secret_ref,
        )
        self.session.add(credential)
        await self.session.commit()

        response = await self.auth_client.delete(f"/credentials/{cred_id}")
        self.assertEqual(response.status_code, 204)

        result = await self.session.execute(
            select(Credential).where(Credential.id == cred_id)
        )
        self.assertIsNone(result.scalar_one_or_none())

        self.assertNotIn(secret_ref, self.mock_providers["secret"].secrets)


if __name__ == "__main__":
    unittest.main()
