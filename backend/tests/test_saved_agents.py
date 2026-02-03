"""Tests for saved agents (templates) routes."""

import unittest

from sqlalchemy import select

from app.models import SavedAgent
from tests.base import AsyncTestCase


class TestListSavedAgents(AsyncTestCase):
    """Tests for listing saved agents."""

    async def test_list_saved_agents_requires_auth(self):
        """Test that listing saved agents requires authentication."""
        response = await self.client.get("/saved-agents")
        self.assertEqual(response.status_code, 403)

    async def test_list_saved_agents_empty(self):
        """Test listing saved agents when user has none."""
        response = await self.auth_client.get("/saved-agents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["saved_agents"], [])
        self.assertEqual(data["total"], 0)

    async def test_list_saved_agents_pagination(self):
        """Test saved agents listing pagination."""
        for i in range(5):
            saved_agent = SavedAgent(
                id=f"saved-{i}",
                user_id=self.test_user.id,
                name=f"Template {i}",
                platform_type="openclaw",
            )
            self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.get("/saved-agents?skip=0&limit=2")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["saved_agents"]), 2)
        self.assertEqual(data["total"], 5)

    async def test_list_starred_only(self):
        """Test filtering for starred saved agents only."""
        for i in range(3):
            saved_agent = SavedAgent(
                id=f"starred-{i}",
                user_id=self.test_user.id,
                name=f"Starred {i}",
                platform_type="openclaw",
                is_starred=True,
            )
            self.session.add(saved_agent)

        for i in range(2):
            saved_agent = SavedAgent(
                id=f"unstarred-{i}",
                user_id=self.test_user.id,
                name=f"Unstarred {i}",
                platform_type="openclaw",
                is_starred=False,
            )
            self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.get("/saved-agents?starred_only=true")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 3)
        for sa in data["saved_agents"]:
            self.assertTrue(sa["is_starred"])


class TestGetSavedAgent(AsyncTestCase):
    """Tests for getting a single saved agent."""

    async def test_get_saved_agent_not_found(self):
        """Test getting non-existent saved agent."""
        response = await self.auth_client.get("/saved-agents/nonexistent-id")
        self.assertEqual(response.status_code, 404)

    async def test_get_saved_agent_success(self):
        """Test successful saved agent retrieval."""
        saved_agent = SavedAgent(
            id="test-saved-123",
            user_id=self.test_user.id,
            name="Test Template",
            platform_type="openclaw",
            description="A test template",
        )
        self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.get("/saved-agents/test-saved-123")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["id"], "test-saved-123")
        self.assertEqual(data["name"], "Test Template")
        self.assertEqual(data["description"], "A test template")


class TestUpdateSavedAgent(AsyncTestCase):
    """Tests for updating saved agents."""

    async def test_update_saved_agent_name(self):
        """Test updating saved agent name."""
        saved_agent = SavedAgent(
            id="update-test",
            user_id=self.test_user.id,
            name="Old Name",
            platform_type="openclaw",
        )
        self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.put(
            "/saved-agents/update-test",
            json={"name": "New Name"},
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["name"], "New Name")

    async def test_update_saved_agent_description(self):
        """Test updating saved agent description."""
        saved_agent = SavedAgent(
            id="desc-test",
            user_id=self.test_user.id,
            name="Template",
            platform_type="openclaw",
        )
        self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.put(
            "/saved-agents/desc-test",
            json={"description": "New description"},
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["description"], "New description")


class TestDeleteSavedAgent(AsyncTestCase):
    """Tests for deleting saved agents."""

    async def test_delete_saved_agent_success(self):
        """Test successful saved agent deletion."""
        saved_agent = SavedAgent(
            id="delete-test",
            user_id=self.test_user.id,
            name="Delete Me",
            platform_type="openclaw",
        )
        self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.delete("/saved-agents/delete-test")
        self.assertEqual(response.status_code, 204)

        result = await self.session.execute(
            select(SavedAgent).where(SavedAgent.id == "delete-test")
        )
        self.assertIsNone(result.scalar_one_or_none())


class TestStarSavedAgent(AsyncTestCase):
    """Tests for starring/unstarring saved agents."""

    async def test_star_saved_agent(self):
        """Test starring a saved agent."""
        saved_agent = SavedAgent(
            id="star-test",
            user_id=self.test_user.id,
            name="Star Me",
            platform_type="openclaw",
            is_starred=False,
        )
        self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.post("/saved-agents/star-test/star")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["is_starred"])

    async def test_unstar_saved_agent(self):
        """Test unstarring a saved agent."""
        saved_agent = SavedAgent(
            id="unstar-test",
            user_id=self.test_user.id,
            name="Unstar Me",
            platform_type="openclaw",
            is_starred=True,
        )
        self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.delete("/saved-agents/unstar-test/star")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertFalse(data["is_starred"])


class TestCopySavedAgent(AsyncTestCase):
    """Tests for copying saved agents."""

    async def test_copy_saved_agent_default_name(self):
        """Test copying a saved agent with default name."""
        saved_agent = SavedAgent(
            id="copy-source",
            user_id=self.test_user.id,
            name="Original",
            platform_type="openclaw",
            description="Original description",
            config_snapshot={"vm_size": "e2-medium"},
        )
        self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.post("/saved-agents/copy-source/copy")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["name"], "Original (copy)")
        self.assertEqual(data["platform_type"], "openclaw")
        self.assertEqual(data["description"], "Original description")
        self.assertEqual(data["config_snapshot"], {"vm_size": "e2-medium"})
        self.assertFalse(data["is_starred"])

    async def test_copy_saved_agent_custom_name(self):
        """Test copying a saved agent with custom name."""
        saved_agent = SavedAgent(
            id="copy-custom",
            user_id=self.test_user.id,
            name="Source",
            platform_type="openclaw",
        )
        self.session.add(saved_agent)
        await self.session.commit()

        response = await self.auth_client.post(
            "/saved-agents/copy-custom/copy",
            params={"name": "My Custom Copy"},
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["name"], "My Custom Copy")


if __name__ == "__main__":
    unittest.main()
