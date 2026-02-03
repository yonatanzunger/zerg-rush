"""Tests for audit logs routes."""

import unittest
from datetime import datetime, timedelta, timezone

from app.models import AuditLog
from tests.base import AsyncTestCase


class TestListAuditLogs(AsyncTestCase):
    """Tests for listing audit logs."""

    async def test_list_logs_requires_auth(self):
        """Test that listing logs requires authentication."""
        response = await self.client.get("/logs")
        self.assertEqual(response.status_code, 403)

    async def test_list_logs_empty(self):
        """Test listing logs when user has none."""
        response = await self.auth_client.get("/logs")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["logs"], [])
        self.assertEqual(data["total"], 0)
        self.assertFalse(data["has_more"])

    async def test_list_logs_pagination(self):
        """Test logs listing pagination."""
        for i in range(10):
            log = AuditLog(
                id=f"log-{i}",
                user_id=self.test_user.id,
                action_type="test.action",
                target_type="test",
                target_id=f"target-{i}",
                timestamp=datetime.now(timezone.utc),
            )
            self.session.add(log)
        await self.session.commit()

        response = await self.auth_client.get("/logs?skip=0&limit=3")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["logs"]), 3)
        self.assertEqual(data["total"], 10)
        self.assertTrue(data["has_more"])

        response = await self.auth_client.get("/logs?skip=9&limit=3")
        data = response.json()
        self.assertEqual(len(data["logs"]), 1)
        self.assertFalse(data["has_more"])

    async def test_list_logs_filter_by_action_type(self):
        """Test filtering logs by action type."""
        for action in ["agent.create", "agent.delete", "user.login"]:
            for i in range(2):
                log = AuditLog(
                    id=f"log-{action}-{i}",
                    user_id=self.test_user.id,
                    action_type=action,
                    timestamp=datetime.now(timezone.utc),
                )
                self.session.add(log)
        await self.session.commit()

        response = await self.auth_client.get("/logs?action_type=agent.create")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        for log in data["logs"]:
            self.assertEqual(log["action_type"], "agent.create")

    async def test_list_logs_filter_by_target_type(self):
        """Test filtering logs by target type."""
        for target in ["agent", "credential", "user"]:
            log = AuditLog(
                id=f"log-target-{target}",
                user_id=self.test_user.id,
                action_type="test.action",
                target_type=target,
                timestamp=datetime.now(timezone.utc),
            )
            self.session.add(log)
        await self.session.commit()

        response = await self.auth_client.get("/logs?target_type=agent")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["logs"][0]["target_type"], "agent")

    async def test_list_logs_ordered_by_timestamp_desc(self):
        """Test that logs are ordered by timestamp descending."""
        base_time = datetime.now(timezone.utc)
        for i in range(3):
            log = AuditLog(
                id=f"log-time-{i}",
                user_id=self.test_user.id,
                action_type="test.action",
                timestamp=base_time - timedelta(hours=i),
            )
            self.session.add(log)
        await self.session.commit()

        response = await self.auth_client.get("/logs")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["logs"][0]["id"], "log-time-0")
        self.assertEqual(data["logs"][2]["id"], "log-time-2")


class TestExportAuditLogs(AsyncTestCase):
    """Tests for exporting audit logs."""

    async def test_export_csv(self):
        """Test exporting logs as CSV."""
        log = AuditLog(
            id="export-csv-log",
            user_id=self.test_user.id,
            action_type="agent.create",
            target_type="agent",
            target_id="agent-123",
            details={"name": "Test Agent"},
            ip_address="192.168.1.1",
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add(log)
        await self.session.commit()

        response = await self.auth_client.get("/logs/export?format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("audit_logs.csv", response.headers["content-disposition"])

        content = response.text
        lines = content.strip().split("\n")
        self.assertEqual(len(lines), 2)

        header = lines[0]
        self.assertIn("ID", header)
        self.assertIn("Timestamp", header)
        self.assertIn("Action", header)

        data_row = lines[1]
        self.assertIn("export-csv-log", data_row)
        self.assertIn("agent.create", data_row)

    async def test_export_json(self):
        """Test exporting logs as JSON."""
        log = AuditLog(
            id="export-json-log",
            user_id=self.test_user.id,
            action_type="credential.delete",
            target_type="credential",
            target_id="cred-456",
            details={"name": "Old Key"},
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add(log)
        await self.session.commit()

        response = await self.auth_client.get("/logs/export?format=json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertIn("audit_logs.json", response.headers["content-disposition"])

        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "export-json-log")
        self.assertEqual(data[0]["action_type"], "credential.delete")
        self.assertEqual(data[0]["details"], {"name": "Old Key"})

    async def test_export_empty_logs(self):
        """Test exporting when there are no logs."""
        response = await self.auth_client.get("/logs/export?format=csv")
        self.assertEqual(response.status_code, 200)

        content = response.text
        lines = content.strip().split("\n")
        self.assertEqual(len(lines), 1)


class TestAuditLogIntegrity(AsyncTestCase):
    """Tests for audit log data integrity."""

    async def test_logs_include_all_fields(self):
        """Test that log entries include all expected fields."""
        log = AuditLog(
            id="full-log",
            user_id=self.test_user.id,
            action_type="agent.start",
            target_type="agent",
            target_id="agent-789",
            details={"vm_id": "vm-123", "reason": "user request"},
            ip_address="10.0.0.1",
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add(log)
        await self.session.commit()

        response = await self.auth_client.get("/logs")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(len(data["logs"]), 1)
        log_entry = data["logs"][0]

        self.assertEqual(log_entry["id"], "full-log")
        self.assertEqual(log_entry["action_type"], "agent.start")
        self.assertEqual(log_entry["target_type"], "agent")
        self.assertEqual(log_entry["target_id"], "agent-789")
        self.assertEqual(log_entry["details"], {"vm_id": "vm-123", "reason": "user request"})
        self.assertEqual(log_entry["ip_address"], "10.0.0.1")
        self.assertIn("timestamp", log_entry)

    async def test_logs_user_isolation(self):
        """Test that users can only see their own logs."""
        log = AuditLog(
            id="other-user-log",
            user_id="other-user-id",
            action_type="secret.action",
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add(log)
        await self.session.commit()

        response = await self.auth_client.get("/logs")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["total"], 0)
        self.assertEqual(len(data["logs"]), 0)


if __name__ == "__main__":
    unittest.main()
