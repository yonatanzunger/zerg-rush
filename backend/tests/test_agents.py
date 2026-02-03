"""Tests for agent management routes."""

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.cloud.interfaces import VMInstance, VMStatus
from app.models import ActiveAgent
from tests.base import AsyncTestCase


def make_uuid(suffix: int) -> str:
    """Create a valid UUID string with a predictable suffix for testing."""
    return f"00000000-0000-0000-0000-{suffix:012d}"


class TestListAgents(AsyncTestCase):
    """Tests for listing agents."""

    async def test_list_agents_requires_auth(self):
        """Test that listing agents requires authentication."""
        response = await self.client.get("/agents")
        self.assertEqual(response.status_code, 403)

    async def test_list_agents_empty(self):
        """Test listing agents when user has none."""
        response = await self.auth_client.get("/agents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["agents"], [])
        self.assertEqual(data["total"], 0)

    async def test_list_agents_pagination(self):
        """Test agent listing pagination."""
        for i in range(5):
            agent = ActiveAgent(
                id=make_uuid(i),
                user_id=self.test_user.id,
                name=f"Agent {i}",
                vm_id=f"vm-{i}",
                vm_size="e2-small",
                vm_status="running",
                bucket_id=f"bucket-{i}",
                platform_type="openclaw",
            )
            self.session.add(agent)
        await self.session.commit()

        response = await self.auth_client.get("/agents?skip=0&limit=2")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["agents"]), 2)
        self.assertEqual(data["total"], 5)

        response = await self.auth_client.get("/agents?skip=3&limit=10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["agents"]), 2)


class TestCreateAgent(AsyncTestCase):
    """Tests for creating agents."""

    async def test_create_agent_requires_auth(self):
        """Test that creating agents requires authentication."""
        response = await self.client.post(
            "/agents",
            json={"name": "Test Agent"},
        )
        self.assertEqual(response.status_code, 403)

    async def test_create_agent_success(self):
        """Test successful agent creation."""
        response = await self.auth_client.post(
            "/agents",
            json={"name": "Test Agent", "platform_type": "openclaw"},
        )
        self.assertEqual(response.status_code, 201)

        data = response.json()
        self.assertEqual(data["name"], "Test Agent")
        self.assertEqual(data["platform_type"], "openclaw")
        self.assertEqual(data["vm_status"], "running")
        self.assertIsNotNone(data["vm_internal_ip"])

    async def test_create_agent_with_custom_size(self):
        """Test creating agent with custom VM size."""
        response = await self.auth_client.post(
            "/agents",
            json={
                "name": "Big Agent",
                "platform_type": "openclaw",
                "vm_size": "e2-medium",
            },
        )
        self.assertEqual(response.status_code, 201)

        data = response.json()
        self.assertEqual(data["vm_size"], "e2-medium")

    async def test_create_agent_invalid_name(self):
        """Test that empty name is rejected."""
        response = await self.auth_client.post(
            "/agents",
            json={"name": ""},
        )
        self.assertEqual(response.status_code, 422)


class TestGetAgent(AsyncTestCase):
    """Tests for getting a single agent."""

    async def test_get_agent_requires_auth(self):
        """Test that getting agent requires authentication."""
        response = await self.client.get("/agents/some-id")
        self.assertEqual(response.status_code, 403)

    async def test_get_agent_not_found(self):
        """Test getting non-existent agent."""
        response = await self.auth_client.get("/agents/nonexistent-id")
        self.assertEqual(response.status_code, 404)

    async def test_get_agent_success(self):
        """Test successful agent retrieval."""
        agent_id = make_uuid(100)
        agent = ActiveAgent(
            id=agent_id,
            user_id=self.test_user.id,
            name="Test Agent",
            vm_id="vm-123",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-123",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        response = await self.auth_client.get(f"/agents/{agent_id}")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["id"], agent_id)
        self.assertEqual(data["name"], "Test Agent")

    async def test_get_agent_other_user(self):
        """Test that users cannot access other users' agents."""
        agent_id = make_uuid(101)
        other_user_id = make_uuid(999)
        agent = ActiveAgent(
            id=agent_id,
            user_id=other_user_id,
            name="Other Agent",
            vm_id="vm-other",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-other",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        response = await self.auth_client.get(f"/agents/{agent_id}")
        self.assertEqual(response.status_code, 404)


class TestDeleteAgent(AsyncTestCase):
    """Tests for deleting agents."""

    async def test_delete_agent_requires_auth(self):
        """Test that deleting agent requires authentication."""
        response = await self.client.delete("/agents/some-id")
        self.assertEqual(response.status_code, 403)

    async def test_delete_agent_not_found(self):
        """Test deleting non-existent agent."""
        response = await self.auth_client.delete("/agents/nonexistent-id")
        self.assertEqual(response.status_code, 404)

    async def test_delete_agent_success(self):
        """Test successful agent deletion."""
        agent_id = make_uuid(200)
        agent = ActiveAgent(
            id=agent_id,
            user_id=self.test_user.id,
            name="Delete Me",
            vm_id="vm-delete",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-delete",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        response = await self.auth_client.delete(f"/agents/{agent_id}")
        self.assertEqual(response.status_code, 204)

        result = await self.session.execute(
            select(ActiveAgent).where(ActiveAgent.id == agent_id)
        )
        self.assertIsNone(result.scalar_one_or_none())


class TestAgentLifecycle(AsyncTestCase):
    """Tests for agent start/stop lifecycle."""

    async def test_start_agent_requires_auth(self):
        """Test that starting agent requires authentication."""
        response = await self.client.post("/agents/some-id/start")
        self.assertEqual(response.status_code, 403)

    async def test_stop_agent_requires_auth(self):
        """Test that stopping agent requires authentication."""
        response = await self.client.post("/agents/some-id/stop")
        self.assertEqual(response.status_code, 403)

    async def test_start_stopped_agent(self):
        """Test starting a stopped agent."""
        agent_id = make_uuid(300)
        agent = ActiveAgent(
            id=agent_id,
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

        self.mock_providers["vm"].vms["vm-stopped"] = VMInstance(
            vm_id="vm-stopped",
            name="Stopped Agent",
            status=VMStatus.STOPPED,
            internal_ip="http://10.0.0.2:8080",
            external_ip=None,
            created_at=datetime.now(timezone.utc),
            zone="us-central1-a",
        )

        response = await self.auth_client.post(f"/agents/{agent_id}/start")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["vm_status"], "running")

    async def test_stop_running_agent(self):
        """Test stopping a running agent."""
        agent_id = make_uuid(301)
        agent = ActiveAgent(
            id=agent_id,
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

        self.mock_providers["vm"].vms["vm-running"] = VMInstance(
            vm_id="vm-running",
            name="Running Agent",
            status=VMStatus.RUNNING,
            internal_ip="http://10.0.0.3:8080",
            external_ip=None,
            created_at=datetime.now(timezone.utc),
            zone="us-central1-a",
        )

        response = await self.auth_client.post(f"/agents/{agent_id}/stop")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["vm_status"], "stopped")

    async def test_start_already_running_agent(self):
        """Test that starting an already running agent fails."""
        agent_id = make_uuid(302)
        agent = ActiveAgent(
            id=agent_id,
            user_id=self.test_user.id,
            name="Running",
            vm_id="vm-already",
            vm_size="e2-small",
            vm_status="running",
            bucket_id="bucket-already",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        response = await self.auth_client.post(f"/agents/{agent_id}/start")
        self.assertEqual(response.status_code, 400)


class TestAgentStatus(AsyncTestCase):
    """Tests for agent status endpoint."""

    async def test_get_status_refreshes_from_cloud(self):
        """Test that status endpoint refreshes from cloud provider."""
        agent_id = make_uuid(400)
        agent = ActiveAgent(
            id=agent_id,
            user_id=self.test_user.id,
            name="Status Agent",
            vm_id="vm-status",
            vm_size="e2-small",
            vm_status="creating",
            bucket_id="bucket-status",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        self.mock_providers["vm"].vms["vm-status"] = VMInstance(
            vm_id="vm-status",
            name="Status Agent",
            status=VMStatus.RUNNING,
            internal_ip="http://10.0.0.4:8080",
            external_ip=None,
            created_at=datetime.now(timezone.utc),
            zone="us-central1-a",
        )

        response = await self.auth_client.get(f"/agents/{agent_id}/status")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["vm_status"], "running")


class TestArchiveAgent(AsyncTestCase):
    """Tests for archiving agents."""

    async def test_archive_agent_creates_saved_agent(self):
        """Test that archiving creates a saved agent template."""
        agent_id = make_uuid(500)
        agent = ActiveAgent(
            id=agent_id,
            user_id=self.test_user.id,
            name="Archive Me",
            vm_id="vm-archive",
            vm_size="e2-medium",
            vm_status="running",
            bucket_id="bucket-archive",
            platform_type="openclaw",
        )
        self.session.add(agent)
        await self.session.commit()

        response = await self.auth_client.post(
            f"/agents/{agent_id}/archive",
            params={"name": "My Template"},
        )
        self.assertEqual(response.status_code, 201)

        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["name"], "My Template")


if __name__ == "__main__":
    unittest.main()
