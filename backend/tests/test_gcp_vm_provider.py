"""Unit tests for GCP VM provider with mocked SDK."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.cloud.interfaces import VMConfig, VMStatus


class TestGCPVMProviderConstruction(unittest.IsolatedAsyncioTestCase):
    """Tests for GCPVMProvider request construction."""

    def setUp(self):
        """Set up mocks for GCP SDK."""
        # Patch compute_v1 before importing the provider
        self.compute_patcher = patch("app.cloud.gcp.vm.compute_v1")
        self.mock_compute = self.compute_patcher.start()

        # Set up mock clients
        self.mock_instances_client = MagicMock()
        self.mock_operations_client = MagicMock()
        self.mock_compute.InstancesClient.return_value = self.mock_instances_client
        self.mock_compute.ZoneOperationsClient.return_value = self.mock_operations_client

        # Make the mock classes return MagicMock instances that track attribute assignments
        self.mock_compute.Instance.return_value = MagicMock()
        self.mock_compute.AttachedDisk.return_value = MagicMock()
        self.mock_compute.AttachedDiskInitializeParams.return_value = MagicMock()
        self.mock_compute.NetworkInterface.return_value = MagicMock()
        self.mock_compute.Metadata.return_value = MagicMock()
        self.mock_compute.InsertInstanceRequest.return_value = MagicMock()
        self.mock_compute.WaitZoneOperationRequest.return_value = MagicMock()
        self.mock_compute.GetInstanceRequest.return_value = MagicMock()

        # Set up enum values
        self.mock_compute.AttachedDisk.Type.PERSISTENT = "PERSISTENT"

        # Patch settings
        self.settings_patcher = patch("app.cloud.gcp.vm.get_settings")
        self.mock_settings = self.settings_patcher.start()
        self.mock_settings.return_value = MagicMock(
            gcp_project_id="test-project",
            gcp_zone="us-central1-a",
            gcp_agent_network="test-network",
            gcp_agent_subnet="test-subnet",
        )

    def tearDown(self):
        """Stop patchers."""
        self.compute_patcher.stop()
        self.settings_patcher.stop()

    async def test_create_vm_sets_correct_machine_type(self):
        """Test that machine type is formatted correctly."""
        from app.cloud.gcp.vm import GCPVMProvider

        # Set up mock operation response
        mock_operation = MagicMock()
        mock_operation.name = "operation-123"
        self.mock_instances_client.insert.return_value = mock_operation

        # Set up mock get response for the return value
        mock_instance = MagicMock()
        mock_instance.name = "test-vm"
        mock_instance.status = "RUNNING"
        mock_instance.network_interfaces = []
        mock_instance.creation_timestamp = "2024-01-01T00:00:00Z"
        mock_instance.labels = {}
        self.mock_instances_client.get.return_value = mock_instance

        provider = GCPVMProvider()
        config = VMConfig(
            name="test-vm",
            size="e2-small",
            image="default",
            user_id="user-123",
            agent_id="agent-456",
        )

        await provider.create_vm(config)

        # Verify Instance was created with correct machine_type
        instance = self.mock_compute.Instance.return_value
        self.assertEqual(
            instance.machine_type, "zones/us-central1-a/machineTypes/e2-small"
        )

    async def test_create_vm_with_startup_script_uses_dict_metadata(self):
        """Test that startup script metadata uses dict format, not compute_v1.Items."""
        from app.cloud.gcp.vm import GCPVMProvider

        # Set up mock operation response
        mock_operation = MagicMock()
        mock_operation.name = "operation-123"
        self.mock_instances_client.insert.return_value = mock_operation

        # Set up mock get response
        mock_instance = MagicMock()
        mock_instance.name = "test-vm"
        mock_instance.status = "RUNNING"
        mock_instance.network_interfaces = []
        mock_instance.creation_timestamp = "2024-01-01T00:00:00Z"
        mock_instance.labels = {}
        self.mock_instances_client.get.return_value = mock_instance

        provider = GCPVMProvider()
        config = VMConfig(
            name="test-vm",
            size="e2-small",
            image="default",
            user_id="user-123",
            agent_id="agent-456",
            startup_script="#!/bin/bash\necho hello",
        )

        await provider.create_vm(config)

        # Verify Metadata was created
        self.mock_compute.Metadata.assert_called_once()
        metadata = self.mock_compute.Metadata.return_value

        # The critical test: metadata.items should be a list of dicts
        self.assertIsInstance(metadata.items, list)
        self.assertEqual(len(metadata.items), 1)
        self.assertIsInstance(metadata.items[0], dict)
        self.assertEqual(metadata.items[0]["key"], "startup-script")
        self.assertEqual(metadata.items[0]["value"], "#!/bin/bash\necho hello")

    async def test_create_vm_without_startup_script_skips_metadata(self):
        """Test that metadata is not set when no startup script is provided."""
        from app.cloud.gcp.vm import GCPVMProvider

        # Set up mock operation response
        mock_operation = MagicMock()
        mock_operation.name = "operation-123"
        self.mock_instances_client.insert.return_value = mock_operation

        # Set up mock get response
        mock_instance = MagicMock()
        mock_instance.name = "test-vm"
        mock_instance.status = "RUNNING"
        mock_instance.network_interfaces = []
        mock_instance.creation_timestamp = "2024-01-01T00:00:00Z"
        mock_instance.labels = {}
        self.mock_instances_client.get.return_value = mock_instance

        provider = GCPVMProvider()
        config = VMConfig(
            name="test-vm",
            size="e2-small",
            image="default",
            user_id="user-123",
            agent_id="agent-456",
            startup_script=None,
        )

        await provider.create_vm(config)

        # Metadata should not be created when no startup script
        self.mock_compute.Metadata.assert_not_called()

    async def test_create_vm_sets_correct_labels(self):
        """Test that labels are set correctly with sanitized IDs."""
        from app.cloud.gcp.vm import GCPVMProvider

        # Set up mock operation response
        mock_operation = MagicMock()
        mock_operation.name = "operation-123"
        self.mock_instances_client.insert.return_value = mock_operation

        # Set up mock get response
        mock_instance = MagicMock()
        mock_instance.name = "test-vm"
        mock_instance.status = "RUNNING"
        mock_instance.network_interfaces = []
        mock_instance.creation_timestamp = "2024-01-01T00:00:00Z"
        mock_instance.labels = {}
        self.mock_instances_client.get.return_value = mock_instance

        provider = GCPVMProvider()
        config = VMConfig(
            name="test-vm",
            size="e2-small",
            image="default",
            user_id="user-123-456",
            agent_id="agent-789-abc",
            labels={"environment": "test"},
        )

        await provider.create_vm(config)

        instance = self.mock_compute.Instance.return_value
        self.assertEqual(instance.labels["zerg-rush"], "agent")
        self.assertEqual(instance.labels["user-id"], "user123456")  # Dashes removed
        self.assertEqual(instance.labels["agent-id"], "agent789abc")  # Dashes removed
        self.assertEqual(instance.labels["environment"], "test")

    async def test_create_vm_configures_network_interface(self):
        """Test that network interface is configured correctly."""
        from app.cloud.gcp.vm import GCPVMProvider

        # Set up mock operation response
        mock_operation = MagicMock()
        mock_operation.name = "operation-123"
        self.mock_instances_client.insert.return_value = mock_operation

        # Set up mock get response
        mock_instance = MagicMock()
        mock_instance.name = "test-vm"
        mock_instance.status = "RUNNING"
        mock_instance.network_interfaces = []
        mock_instance.creation_timestamp = "2024-01-01T00:00:00Z"
        mock_instance.labels = {}
        self.mock_instances_client.get.return_value = mock_instance

        provider = GCPVMProvider()
        config = VMConfig(
            name="test-vm",
            size="e2-small",
            image="default",
            user_id="user-123",
            agent_id="agent-456",
        )

        await provider.create_vm(config)

        network_interface = self.mock_compute.NetworkInterface.return_value
        self.assertEqual(
            network_interface.network,
            "projects/test-project/global/networks/test-network",
        )
        self.assertEqual(
            network_interface.subnetwork,
            "projects/test-project/regions/us-central1/subnetworks/test-subnet",
        )

    async def test_create_vm_uses_default_image(self):
        """Test that default Ubuntu image is used when image is 'default'."""
        from app.cloud.gcp.vm import GCPVMProvider

        # Set up mock operation response
        mock_operation = MagicMock()
        mock_operation.name = "operation-123"
        self.mock_instances_client.insert.return_value = mock_operation

        # Set up mock get response
        mock_instance = MagicMock()
        mock_instance.name = "test-vm"
        mock_instance.status = "RUNNING"
        mock_instance.network_interfaces = []
        mock_instance.creation_timestamp = "2024-01-01T00:00:00Z"
        mock_instance.labels = {}
        self.mock_instances_client.get.return_value = mock_instance

        provider = GCPVMProvider()
        config = VMConfig(
            name="test-vm",
            size="e2-small",
            image="default",
            user_id="user-123",
            agent_id="agent-456",
        )

        await provider.create_vm(config)

        init_params = self.mock_compute.AttachedDiskInitializeParams.return_value
        self.assertEqual(
            init_params.source_image,
            "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts",
        )


class TestGCPVMProviderStatusMapping(unittest.TestCase):
    """Tests for VM status mapping."""

    def setUp(self):
        """Set up mocks."""
        self.compute_patcher = patch("app.cloud.gcp.vm.compute_v1")
        self.mock_compute = self.compute_patcher.start()
        self.mock_compute.InstancesClient.return_value = MagicMock()
        self.mock_compute.ZoneOperationsClient.return_value = MagicMock()

        self.settings_patcher = patch("app.cloud.gcp.vm.get_settings")
        self.mock_settings = self.settings_patcher.start()
        self.mock_settings.return_value = MagicMock(
            gcp_project_id="test-project",
            gcp_zone="us-central1-a",
            gcp_agent_network="test-network",
            gcp_agent_subnet="test-subnet",
        )

    def tearDown(self):
        """Stop patchers."""
        self.compute_patcher.stop()
        self.settings_patcher.stop()

    def test_status_mapping_running(self):
        """Test RUNNING maps to VMStatus.RUNNING."""
        from app.cloud.gcp.vm import GCPVMProvider

        provider = GCPVMProvider()
        self.assertEqual(provider._map_status("RUNNING"), VMStatus.RUNNING)

    def test_status_mapping_provisioning(self):
        """Test PROVISIONING maps to VMStatus.CREATING."""
        from app.cloud.gcp.vm import GCPVMProvider

        provider = GCPVMProvider()
        self.assertEqual(provider._map_status("PROVISIONING"), VMStatus.CREATING)

    def test_status_mapping_staging(self):
        """Test STAGING maps to VMStatus.CREATING."""
        from app.cloud.gcp.vm import GCPVMProvider

        provider = GCPVMProvider()
        self.assertEqual(provider._map_status("STAGING"), VMStatus.CREATING)

    def test_status_mapping_stopped(self):
        """Test STOPPED maps to VMStatus.STOPPED."""
        from app.cloud.gcp.vm import GCPVMProvider

        provider = GCPVMProvider()
        self.assertEqual(provider._map_status("STOPPED"), VMStatus.STOPPED)

    def test_status_mapping_terminated(self):
        """Test TERMINATED maps to VMStatus.STOPPED."""
        from app.cloud.gcp.vm import GCPVMProvider

        provider = GCPVMProvider()
        self.assertEqual(provider._map_status("TERMINATED"), VMStatus.STOPPED)

    def test_status_mapping_unknown(self):
        """Test unknown status maps to VMStatus.ERROR."""
        from app.cloud.gcp.vm import GCPVMProvider

        provider = GCPVMProvider()
        self.assertEqual(provider._map_status("UNKNOWN_STATUS"), VMStatus.ERROR)


class TestGCPVMProviderWithUserCredentials(unittest.IsolatedAsyncioTestCase):
    """Tests for GCPVMProvider with user OAuth credentials."""

    def setUp(self):
        """Set up mocks."""
        self.compute_patcher = patch("app.cloud.gcp.vm.compute_v1")
        self.mock_compute = self.compute_patcher.start()
        self.mock_compute.InstancesClient.return_value = MagicMock()
        self.mock_compute.ZoneOperationsClient.return_value = MagicMock()

        self.oauth_patcher = patch("app.cloud.gcp.vm.OAuthCredentials")
        self.mock_oauth = self.oauth_patcher.start()

        self.settings_patcher = patch("app.cloud.gcp.vm.get_settings")
        self.mock_settings = self.settings_patcher.start()
        self.mock_settings.return_value = MagicMock(
            gcp_project_id="default-project",
            gcp_zone="us-central1-a",
            gcp_agent_network="test-network",
            gcp_agent_subnet="test-subnet",
        )

    def tearDown(self):
        """Stop patchers."""
        self.compute_patcher.stop()
        self.oauth_patcher.stop()
        self.settings_patcher.stop()

    def test_uses_user_credentials_when_provided(self):
        """Test that user OAuth credentials are used when provided."""
        from app.cloud.gcp.vm import GCPVMProvider
        from app.cloud.interfaces import UserCredentials

        user_creds = UserCredentials(
            access_token="user-token-123",
            project_id="user-project",
        )

        provider = GCPVMProvider(user_credentials=user_creds)

        # Verify OAuth credentials were created with user token
        self.mock_oauth.assert_called_once_with(token="user-token-123")

        # Verify user's project is used
        self.assertEqual(provider.project_id, "user-project")

    def test_uses_default_project_when_user_has_none(self):
        """Test fallback to default project when user doesn't specify one."""
        from app.cloud.gcp.vm import GCPVMProvider
        from app.cloud.interfaces import UserCredentials

        user_creds = UserCredentials(
            access_token="user-token-123",
            project_id=None,
        )

        provider = GCPVMProvider(user_credentials=user_creds)

        # Should fall back to settings project
        self.assertEqual(provider.project_id, "default-project")

    def test_uses_application_default_when_no_user_credentials(self):
        """Test that application default credentials are used when no user creds."""
        from app.cloud.gcp.vm import GCPVMProvider

        provider = GCPVMProvider(user_credentials=None)

        # OAuth should not be called
        self.mock_oauth.assert_not_called()

        # Default project should be used
        self.assertEqual(provider.project_id, "default-project")


if __name__ == "__main__":
    unittest.main()
