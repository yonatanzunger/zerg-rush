"""Tests to verify data isolation between users.

These tests ensure that data created by one user cannot be accessed,
modified, or deleted by another user.
"""

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.auth import create_access_token
from app.cloud.interfaces import VMInstance, VMStatus
from app.models import ActiveAgent, AuditLog, Credential, SavedAgent, User
from tests.base import AsyncTestCase


def make_uuid(suffix: int) -> str:
    """Create a valid UUID string with a predictable suffix for testing."""
    return f"00000000-0000-0000-0000-{suffix:012d}"


class UserIsolationTestCase(AsyncTestCase):
    """Base test case with two users for isolation testing."""

    second_user: User = None
    second_auth_client: AsyncClient = None

    async def asyncSetUp(self):
        """Set up test fixtures with two users."""
        await super().asyncSetUp()

        # Create a second user
        self.second_user = User(
            id=str(uuid4()),
            email="other@example.com",
            name="Other User",
            oauth_provider="google",
            oauth_subject="google-789012",
            last_login=datetime.now(timezone.utc),
        )
        self.session.add(self.second_user)
        await self.session.commit()
        await self.session.refresh(self.second_user)

        # Create auth client for second user
        token = create_access_token(self.second_user.id)
        self.second_auth_client = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def asyncTearDown(self):
        """Clean up test fixtures."""
        if self.second_auth_client:
            await self.second_auth_client.aclose()
        await super().asyncTearDown()


class TestAgentIsolation(UserIsolationTestCase):
    """Tests for agent isolation between users."""

    async def test_list_agents_only_shows_own_agents(self):
        """Test that listing agents only returns the user's own agents."""
        # Create agent for first user
        agent1 = ActiveAgent(
            id=make_uuid(1),
            user_id=self.test_user.id,
            name="User 1 Agent",
            vm_id="vm-1",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-1",
            platform_type="openclaw",
        )
        # Create agent for second user
        agent2 = ActiveAgent(
            id=make_uuid(2),
            user_id=self.second_user.id,
            name="User 2 Agent",
            vm_id="vm-2",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-2",
            platform_type="openclaw",
        )
        self.session.add_all([agent1, agent2])
        await self.session.commit()

        # First user should only see their agent
        response = await self.auth_client.get("/agents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["agents"][0]["id"], make_uuid(1))
        self.assertEqual(data["agents"][0]["name"], "User 1 Agent")

        # Second user should only see their agent
        response = await self.second_auth_client.get("/agents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["agents"][0]["id"], make_uuid(2))
        self.assertEqual(data["agents"][0]["name"], "User 2 Agent")

    async def test_cannot_get_other_users_agent(self):
        """Test that a user cannot get another user's agent details."""
        agent = ActiveAgent(
            id=make_uuid(10),
            user_id=self.test_user.id,
            name="Private Agent",
            vm_id="vm-private",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-private",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        # Second user tries to access first user's agent
        response = await self.second_auth_client.get(f"/agents/{make_uuid(10)}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Agent not found")

    async def test_cannot_delete_other_users_agent(self):
        """Test that a user cannot delete another user's agent."""
        agent = ActiveAgent(
            id=make_uuid(20),
            user_id=self.test_user.id,
            name="Protected Agent",
            vm_id="vm-protected",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-protected",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        # Second user tries to delete first user's agent
        response = await self.second_auth_client.delete(f"/agents/{make_uuid(20)}")
        self.assertEqual(response.status_code, 404)

        # Verify agent still exists
        result = await self.session.execute(
            select(ActiveAgent).where(ActiveAgent.id == make_uuid(20))
        )
        self.assertIsNotNone(result.scalar_one_or_none())

    async def test_cannot_start_other_users_agent(self):
        """Test that a user cannot start another user's agent."""
        agent = ActiveAgent(
            id=make_uuid(30),
            user_id=self.test_user.id,
            name="Stopped Agent",
            vm_id="vm-stopped",
            vm_size="e2-small",
            vm_status="stopped",
            bucket_id="bucket-stopped",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        # Second user tries to start first user's agent
        response = await self.second_auth_client.post(f"/agents/{make_uuid(30)}/start")
        self.assertEqual(response.status_code, 404)

    async def test_cannot_stop_other_users_agent(self):
        """Test that a user cannot stop another user's agent."""
        agent = ActiveAgent(
            id=make_uuid(40),
            user_id=self.test_user.id,
            name="Running Agent",
            vm_id="vm-running",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-running",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        # Second user tries to stop first user's agent
        response = await self.second_auth_client.post(f"/agents/{make_uuid(40)}/stop")
        self.assertEqual(response.status_code, 404)

    async def test_cannot_get_status_of_other_users_agent(self):
        """Test that a user cannot get status of another user's agent."""
        agent = ActiveAgent(
            id=make_uuid(50),
            user_id=self.test_user.id,
            name="Status Agent",
            vm_id="vm-status",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-status",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        # Second user tries to get status of first user's agent
        response = await self.second_auth_client.get(f"/agents/{make_uuid(50)}/status")
        self.assertEqual(response.status_code, 404)

    async def test_cannot_archive_other_users_agent(self):
        """Test that a user cannot archive another user's agent."""
        agent = ActiveAgent(
            id=make_uuid(60),
            user_id=self.test_user.id,
            name="Archive Target",
            vm_id="vm-archive",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-archive",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        # Second user tries to archive first user's agent
        response = await self.second_auth_client.post(
            f"/agents/{make_uuid(60)}/archive", params={"name": "Stolen Template"}
        )
        self.assertEqual(response.status_code, 404)

    async def test_cannot_chat_with_other_users_agent(self):
        """Test that a user cannot chat with another user's agent."""
        agent = ActiveAgent(
            id=make_uuid(70),
            user_id=self.test_user.id,
            name="Chat Agent",
            vm_id="vm-chat",
            vm_size="e2-small",
            vm_status="running",
            vm_internal_ip="http://10.0.0.1:8080",
            bucket_id="bucket-chat",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        # Second user tries to chat with first user's agent
        response = await self.second_auth_client.post(
            f"/agents/{make_uuid(70)}/chat", json={"message": "Hello"}
        )
        self.assertEqual(response.status_code, 404)

    async def test_cannot_create_agent_with_other_users_template(self):
        """Test that a user cannot create an agent using another user's template."""
        # Create a template for first user
        template = SavedAgent(
            id=make_uuid(80),
            user_id=self.test_user.id,
            name="Private Template",
            platform_type="openclaw",
        )
        self.session.add(template)
        await self.session.commit()

        # Second user tries to create agent with first user's template
        response = await self.second_auth_client.post(
            "/agents",
            json={
                "name": "Malicious Agent",
                "platform_type": "openclaw",
                "template_id": make_uuid(80),
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Template not found")

    async def test_cannot_create_agent_with_other_users_credentials(self):
        """Test that a user cannot grant another user's credentials to an agent."""
        # Create a credential for first user
        credential = Credential(
            id=make_uuid(81),
            user_id=self.test_user.id,
            name="Private API Key",
            type="llm",
            secret_ref="secret-private",
        )
        self.session.add(credential)
        await self.session.commit()

        # Second user tries to create agent with first user's credential
        response = await self.second_auth_client.post(
            "/agents",
            json={
                "name": "Stealing Agent",
                "platform_type": "openclaw",
                "credential_ids": [make_uuid(81)],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "One or more credentials not found")


class TestSavedAgentIsolation(UserIsolationTestCase):
    """Tests for saved agent (template) isolation between users."""

    async def test_list_saved_agents_only_shows_own(self):
        """Test that listing saved agents only returns the user's own templates."""
        # Create saved agent for first user
        template1 = SavedAgent(
            id=make_uuid(100),
            user_id=self.test_user.id,
            name="User 1 Template",
            platform_type="openclaw",
        )
        # Create saved agent for second user
        template2 = SavedAgent(
            id=make_uuid(101),
            user_id=self.second_user.id,
            name="User 2 Template",
            platform_type="openclaw",
        )
        self.session.add_all([template1, template2])
        await self.session.commit()

        # First user should only see their template
        response = await self.auth_client.get("/saved-agents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["saved_agents"][0]["name"], "User 1 Template")

        # Second user should only see their template
        response = await self.second_auth_client.get("/saved-agents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["saved_agents"][0]["name"], "User 2 Template")

    async def test_cannot_get_other_users_saved_agent(self):
        """Test that a user cannot get another user's saved agent."""
        template = SavedAgent(
            id=make_uuid(110),
            user_id=self.test_user.id,
            name="Secret Template",
            platform_type="openclaw",
        )
        self.session.add(template)
        await self.session.commit()

        # Second user tries to access first user's template
        response = await self.second_auth_client.get(f"/saved-agents/{make_uuid(110)}")
        self.assertEqual(response.status_code, 404)

    async def test_cannot_update_other_users_saved_agent(self):
        """Test that a user cannot update another user's saved agent."""
        template = SavedAgent(
            id=make_uuid(120),
            user_id=self.test_user.id,
            name="Protected Template",
            platform_type="openclaw",
        )
        self.session.add(template)
        await self.session.commit()

        # Second user tries to update first user's template
        response = await self.second_auth_client.put(
            f"/saved-agents/{make_uuid(120)}",
            json={"name": "Hijacked Template", "description": "Malicious update"},
        )
        self.assertEqual(response.status_code, 404)

        # Verify template was not modified
        result = await self.session.execute(
            select(SavedAgent).where(SavedAgent.id == make_uuid(120))
        )
        template = result.scalar_one()
        self.assertEqual(template.name, "Protected Template")
        self.assertIsNone(template.description)

    async def test_cannot_delete_other_users_saved_agent(self):
        """Test that a user cannot delete another user's saved agent."""
        template = SavedAgent(
            id=make_uuid(130),
            user_id=self.test_user.id,
            name="Undeletable Template",
            platform_type="openclaw",
        )
        self.session.add(template)
        await self.session.commit()

        # Second user tries to delete first user's template
        response = await self.second_auth_client.delete(
            f"/saved-agents/{make_uuid(130)}"
        )
        self.assertEqual(response.status_code, 404)

        # Verify template still exists
        result = await self.session.execute(
            select(SavedAgent).where(SavedAgent.id == make_uuid(130))
        )
        self.assertIsNotNone(result.scalar_one_or_none())

    async def test_cannot_star_other_users_saved_agent(self):
        """Test that a user cannot star another user's saved agent."""
        template = SavedAgent(
            id=make_uuid(140),
            user_id=self.test_user.id,
            name="Unstarrable Template",
            platform_type="openclaw",
            is_starred=False,
        )
        self.session.add(template)
        await self.session.commit()

        # Second user tries to star first user's template
        response = await self.second_auth_client.post(
            f"/saved-agents/{make_uuid(140)}/star"
        )
        self.assertEqual(response.status_code, 404)

        # Verify template was not starred
        result = await self.session.execute(
            select(SavedAgent).where(SavedAgent.id == make_uuid(140))
        )
        template = result.scalar_one()
        self.assertFalse(template.is_starred)

    async def test_cannot_unstar_other_users_saved_agent(self):
        """Test that a user cannot unstar another user's saved agent."""
        template = SavedAgent(
            id=make_uuid(150),
            user_id=self.test_user.id,
            name="Unstarrable Template",
            platform_type="openclaw",
            is_starred=True,
        )
        self.session.add(template)
        await self.session.commit()

        # Second user tries to unstar first user's template
        response = await self.second_auth_client.delete(
            f"/saved-agents/{make_uuid(150)}/star"
        )
        self.assertEqual(response.status_code, 404)

        # Verify template is still starred
        result = await self.session.execute(
            select(SavedAgent).where(SavedAgent.id == make_uuid(150))
        )
        template = result.scalar_one()
        self.assertTrue(template.is_starred)

    async def test_cannot_copy_other_users_saved_agent(self):
        """Test that a user cannot copy another user's saved agent."""
        template = SavedAgent(
            id=make_uuid(160),
            user_id=self.test_user.id,
            name="Uncopyable Template",
            platform_type="openclaw",
            config_snapshot={"vm_size": "e2-large"},
        )
        self.session.add(template)
        await self.session.commit()

        # Second user tries to copy first user's template
        response = await self.second_auth_client.post(
            f"/saved-agents/{make_uuid(160)}/copy"
        )
        self.assertEqual(response.status_code, 404)


class TestCredentialIsolation(UserIsolationTestCase):
    """Tests for credential isolation between users."""

    async def test_list_credentials_only_shows_own(self):
        """Test that listing credentials only returns the user's own credentials."""
        # Create credential for first user
        cred1 = Credential(
            id=make_uuid(200),
            user_id=self.test_user.id,
            name="User 1 API Key",
            type="llm",
            secret_ref="secret-user1",
        )
        # Create credential for second user
        cred2 = Credential(
            id=make_uuid(201),
            user_id=self.second_user.id,
            name="User 2 API Key",
            type="llm",
            secret_ref="secret-user2",
        )
        self.session.add_all([cred1, cred2])
        await self.session.commit()

        # First user should only see their credential
        response = await self.auth_client.get("/credentials")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["credentials"][0]["name"], "User 1 API Key")

        # Second user should only see their credential
        response = await self.second_auth_client.get("/credentials")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["credentials"][0]["name"], "User 2 API Key")

    async def test_cannot_get_other_users_credential(self):
        """Test that a user cannot get another user's credential."""
        cred = Credential(
            id=make_uuid(210),
            user_id=self.test_user.id,
            name="Secret API Key",
            type="llm",
            secret_ref="secret-private-key",
        )
        self.session.add(cred)
        await self.session.commit()

        # Second user tries to access first user's credential
        response = await self.second_auth_client.get(f"/credentials/{make_uuid(210)}")
        self.assertEqual(response.status_code, 404)

    async def test_cannot_delete_other_users_credential(self):
        """Test that a user cannot delete another user's credential."""
        # Store secret in mock provider
        secret_ref = await self.mock_providers["secret"].store_secret(
            user_id=self.test_user.id,
            name="Protected Key",
            value="super-secret-value",
        )

        cred = Credential(
            id=make_uuid(220),
            user_id=self.test_user.id,
            name="Protected Key",
            type="cloud",
            secret_ref=secret_ref,
        )
        self.session.add(cred)
        await self.session.commit()

        # Second user tries to delete first user's credential
        response = await self.second_auth_client.delete(f"/credentials/{make_uuid(220)}")
        self.assertEqual(response.status_code, 404)

        # Verify credential still exists
        result = await self.session.execute(
            select(Credential).where(Credential.id == make_uuid(220))
        )
        self.assertIsNotNone(result.scalar_one_or_none())

        # Verify secret still exists in provider
        self.assertIn(secret_ref, self.mock_providers["secret"].secrets)


class TestAuditLogIsolation(UserIsolationTestCase):
    """Tests for audit log isolation between users."""

    async def test_list_logs_only_shows_own(self):
        """Test that listing audit logs only returns the user's own logs."""
        # Create log for first user (target_id must be a valid UUID or None)
        log1 = AuditLog(
            id=make_uuid(300),
            user_id=self.test_user.id,
            action_type="agent.create",
            target_type="agent",
            target_id=make_uuid(350),
            timestamp=datetime.now(timezone.utc),
        )
        # Create log for second user
        log2 = AuditLog(
            id=make_uuid(301),
            user_id=self.second_user.id,
            action_type="credential.create",
            target_type="credential",
            target_id=make_uuid(351),
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add_all([log1, log2])
        await self.session.commit()

        # First user should only see their log
        response = await self.auth_client.get("/logs")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["logs"][0]["action_type"], "agent.create")

        # Second user should only see their log
        response = await self.second_auth_client.get("/logs")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["logs"][0]["action_type"], "credential.create")

    async def test_logs_filtered_by_user_even_with_target_filter(self):
        """Test that audit logs are filtered by user even when filtering by target."""
        agent_id = make_uuid(310)

        # Create log for first user
        log1 = AuditLog(
            id=make_uuid(311),
            user_id=self.test_user.id,
            action_type="agent.create",
            target_type="agent",
            target_id=agent_id,
            timestamp=datetime.now(timezone.utc),
        )
        # Create log for second user referencing the same target_id
        log2 = AuditLog(
            id=make_uuid(312),
            user_id=self.second_user.id,
            action_type="agent.view",
            target_type="agent",
            target_id=agent_id,
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add_all([log1, log2])
        await self.session.commit()

        # First user querying by target should only see their own log
        response = await self.auth_client.get(f"/logs?target_id={agent_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["logs"][0]["action_type"], "agent.create")

        # Second user querying by target should only see their own log
        response = await self.second_auth_client.get(f"/logs?target_id={agent_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["logs"][0]["action_type"], "agent.view")


class TestCrossResourceIsolation(UserIsolationTestCase):
    """Tests for isolation across related resources."""

    async def test_agent_deletion_does_not_affect_other_users_agents(self):
        """Test that deleting an agent doesn't affect other users' agents."""
        # Create agents for both users
        agent1 = ActiveAgent(
            id=make_uuid(400),
            user_id=self.test_user.id,
            name="User 1 Agent",
            vm_id="vm-user1",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-user1",
            platform_type="openclaw",
        )
        agent2 = ActiveAgent(
            id=make_uuid(401),
            user_id=self.second_user.id,
            name="User 2 Agent",
            vm_id="vm-user2",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-user2",
            platform_type="openclaw",
        )
        self.session.add_all([agent1, agent2])
        await self.session.commit()

        # First user deletes their agent
        response = await self.auth_client.delete(f"/agents/{make_uuid(400)}")
        self.assertEqual(response.status_code, 204)

        # Second user's agent should still exist
        result = await self.session.execute(
            select(ActiveAgent).where(ActiveAgent.id == make_uuid(401))
        )
        self.assertIsNotNone(result.scalar_one_or_none())

        # Second user can still access their agent
        response = await self.second_auth_client.get(f"/agents/{make_uuid(401)}")
        self.assertEqual(response.status_code, 200)

    async def test_multiple_users_can_have_same_named_resources(self):
        """Test that different users can have resources with the same name."""
        # Both users create agents with the same name
        agent1 = ActiveAgent(
            id=make_uuid(500),
            user_id=self.test_user.id,
            name="My Agent",
            vm_id="vm-user1",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-user1",
            platform_type="openclaw",
        )
        agent2 = ActiveAgent(
            id=make_uuid(501),
            user_id=self.second_user.id,
            name="My Agent",
            vm_id="vm-user2",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-user2",
            platform_type="openclaw",
        )
        self.session.add_all([agent1, agent2])
        await self.session.commit()

        # Each user sees only their own agent
        response = await self.auth_client.get("/agents")
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["agents"][0]["id"], make_uuid(500))

        response = await self.second_auth_client.get("/agents")
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["agents"][0]["id"], make_uuid(501))


if __name__ == "__main__":
    unittest.main()
