"""GCP Compute Engine VM provider implementation."""

import json
from datetime import datetime, timezone
from typing import Any

from google.cloud import compute_v1
from google.api_core.exceptions import NotFound
from google.oauth2.credentials import Credentials as OAuthCredentials

from app.cloud.interfaces import (
    VMProvider,
    VMConfig,
    VMInstance,
    VMStatus,
    CommandResult,
    UserCredentials,
)
from app.config import get_settings
from app.tracing import Session, FunctionTrace


class GCPVMProvider(VMProvider):
    """GCP Compute Engine implementation of VMProvider."""

    def __init__(self, user_credentials: UserCredentials | None = None):
        """Initialize the GCP Compute Engine provider.

        Args:
            user_credentials: Optional user OAuth credentials. If provided,
                these will be used instead of application default credentials.
        """
        settings = get_settings()
        self.zone = settings.gcp_zone
        self.network = settings.gcp_agent_network
        self.subnet = settings.gcp_agent_subnet

        if user_credentials:
            # Use user OAuth credentials
            credentials = OAuthCredentials(token=user_credentials.access_token)
            self.project_id = user_credentials.project_id or settings.gcp_project_id
            self.instances_client = compute_v1.InstancesClient(credentials=credentials)
            self.operations_client = compute_v1.ZoneOperationsClient(
                credentials=credentials
            )
        else:
            # Fall back to application default credentials (for system operations)
            self.project_id = settings.gcp_project_id
            self.instances_client = compute_v1.InstancesClient()
            self.operations_client = compute_v1.ZoneOperationsClient()

    def _map_status(self, gcp_status: str) -> VMStatus:
        """Map GCP status to VMStatus enum."""
        status_map = {
            "PROVISIONING": VMStatus.CREATING,
            "STAGING": VMStatus.CREATING,
            "RUNNING": VMStatus.RUNNING,
            "STOPPING": VMStatus.STOPPING,
            "STOPPED": VMStatus.STOPPED,
            "SUSPENDING": VMStatus.STOPPING,
            "SUSPENDED": VMStatus.STOPPED,
            "TERMINATED": VMStatus.STOPPED,
        }
        return status_map.get(gcp_status, VMStatus.ERROR)

    def _get_vm_image(self, image: str) -> str:
        """Get the full image path for a given image name."""
        # Default to Ubuntu 22.04 LTS
        if not image or image == "default":
            return "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
        return image

    async def create_vm(
        self, config: VMConfig, session: Session | None = None
    ) -> VMInstance:
        """Create a new GCP Compute Engine instance."""
        with FunctionTrace(
            session,
            "Creating GCE VM",
            name=config.name,
            size=config.size,
            agent_id=config.agent_id,
        ) as trace:
            # Build instance configuration
            instance = compute_v1.Instance()
            instance.name = config.name
            instance.machine_type = f"zones/{self.zone}/machineTypes/{config.size}"

            # Boot disk
            disk = compute_v1.AttachedDisk()
            disk.auto_delete = True
            disk.boot = True
            disk.type_ = "PERSISTENT"

            initialize_params = compute_v1.AttachedDiskInitializeParams()
            initialize_params.source_image = self._get_vm_image(config.image)
            initialize_params.disk_size_gb = 20
            initialize_params.disk_type = f"zones/{self.zone}/diskTypes/pd-standard"
            disk.initialize_params = initialize_params
            instance.disks = [disk]

            # Network interface
            network_interface = compute_v1.NetworkInterface()
            network_interface.access_configs = [
                compute_v1.AccessConfig(
                    type_=compute_v1.AccessConfig.Type.ONE_TO_ONE_NAT,
                    network_tier=compute_v1.AccessConfig.NetworkTier.PREMIUM,
                )
            ]
            if self.network != "default":
                network_interface.network = (
                    f"projects/{self.project_id}/global/networks/{self.network}"
                )
                if self.subnet != "default":
                    network_interface.subnetwork = f"projects/{self.project_id}/regions/{self.zone.rsplit('-', 1)[0]}/subnetworks/{self.subnet}"
            instance.network_interfaces = [network_interface]

            # Labels
            instance.labels = {
                "zerg-rush": "agent",
                "user-id": config.user_id.replace("-", ""),
                "agent-id": config.agent_id.replace("-", ""),
            }
            if config.labels:
                instance.labels.update(config.labels)

            # Startup script
            if config.startup_script:
                metadata = compute_v1.Metadata()
                metadata.items = [
                    {"key": "startup-script", "value": config.startup_script}
                ]
                instance.metadata = metadata

            # Create the instance
            request = compute_v1.InsertInstanceRequest()
            request.project = self.project_id
            request.zone = self.zone
            request.instance_resource = instance

            operation = self.instances_client.insert(request=request)

            # Wait for operation to complete
            wait_request = compute_v1.WaitZoneOperationRequest()
            wait_request.project = self.project_id
            wait_request.zone = self.zone
            wait_request.operation = operation.name
            self.operations_client.wait(request=wait_request)

            trace.log("GCE VM created", name=config.name)

            # Get the created instance
            return await self.get_vm_status(config.name, session=session)

    async def delete_vm(self, vm_id: str, session: Session | None = None) -> None:
        """Delete a GCP Compute Engine instance."""
        with FunctionTrace(session, "Deleting GCE VM", vm_id=vm_id) as trace:
            request = compute_v1.DeleteInstanceRequest()
            request.project = self.project_id
            request.zone = self.zone
            request.instance = vm_id

            operation = self.instances_client.delete(request=request)

            # Wait for operation to complete
            wait_request = compute_v1.WaitZoneOperationRequest()
            wait_request.project = self.project_id
            wait_request.zone = self.zone
            wait_request.operation = operation.name
            self.operations_client.wait(request=wait_request)

            trace.log("GCE VM deleted", vm_id=vm_id)

    async def start_vm(self, vm_id: str, session: Session | None = None) -> None:
        """Start a stopped GCP Compute Engine instance."""
        with FunctionTrace(session, "Starting GCE VM", vm_id=vm_id) as trace:
            request = compute_v1.StartInstanceRequest()
            request.project = self.project_id
            request.zone = self.zone
            request.instance = vm_id

            operation = self.instances_client.start(request=request)

            wait_request = compute_v1.WaitZoneOperationRequest()
            wait_request.project = self.project_id
            wait_request.zone = self.zone
            wait_request.operation = operation.name
            self.operations_client.wait(request=wait_request)

            trace.log("GCE VM started", vm_id=vm_id)

    async def stop_vm(self, vm_id: str, session: Session | None = None) -> None:
        """Stop a running GCP Compute Engine instance."""
        with FunctionTrace(session, "Stopping GCE VM", vm_id=vm_id) as trace:
            request = compute_v1.StopInstanceRequest()
            request.project = self.project_id
            request.zone = self.zone
            request.instance = vm_id

            operation = self.instances_client.stop(request=request)

            wait_request = compute_v1.WaitZoneOperationRequest()
            wait_request.project = self.project_id
            wait_request.zone = self.zone
            wait_request.operation = operation.name
            self.operations_client.wait(request=wait_request)

            trace.log("GCE VM stopped", vm_id=vm_id)

    async def get_vm_status(
        self, vm_id: str, session: Session | None = None
    ) -> VMInstance:
        """Get current status of a GCP Compute Engine instance."""
        request = compute_v1.GetInstanceRequest()
        request.project = self.project_id
        request.zone = self.zone
        request.instance = vm_id

        instance = self.instances_client.get(request=request)

        # Get internal IP
        internal_ip = None
        if instance.network_interfaces:
            internal_ip = instance.network_interfaces[0].network_i_p

        # Get external IP if any
        external_ip = None
        if (
            instance.network_interfaces
            and instance.network_interfaces[0].access_configs
        ):
            external_ip = instance.network_interfaces[0].access_configs[0].nat_i_p

        return VMInstance(
            vm_id=instance.name,
            name=instance.name,
            status=self._map_status(instance.status),
            internal_ip=internal_ip,
            external_ip=external_ip,
            created_at=datetime.fromisoformat(
                instance.creation_timestamp.replace("Z", "+00:00")
            ),
            zone=self.zone,
            metadata=dict(instance.labels) if instance.labels else None,
        )

    async def run_command(
        self,
        vm_id: str,
        command: str,
        timeout: int = 300,
        session: Session | None = None,
    ) -> CommandResult:
        """Run a command on a VM using OS Login and SSH.

        Note: This requires OS Login to be enabled on the project/instance
        and appropriate IAM permissions.
        """
        # In production, this would use Google Cloud OS Login with SSH
        # For now, we'll use the serial port or startup script approach
        # This is a simplified implementation
        raise NotImplementedError(
            "Direct command execution requires OS Login setup. "
            "Use startup scripts for initial provisioning."
        )

    async def upload_file(
        self,
        vm_id: str,
        local_content: bytes,
        remote_path: str,
        session: Session | None = None,
    ) -> None:
        """Upload a file to a VM.

        Note: This requires SSH access to the VM.
        """
        raise NotImplementedError(
            "File upload requires SSH access. " "Use Cloud Storage for file exchange."
        )

    async def download_file(
        self, vm_id: str, remote_path: str, session: Session | None = None
    ) -> bytes:
        """Download a file from a VM.

        Note: This requires SSH access to the VM.
        """
        raise NotImplementedError(
            "File download requires SSH access. " "Use Cloud Storage for file exchange."
        )

    async def list_files(
        self, vm_id: str, path: str, session: Session | None = None
    ) -> list[dict[str, Any]]:
        """List files in a directory on a VM.

        Note: This requires SSH access to the VM.
        """
        raise NotImplementedError(
            "File listing requires SSH access. " "Use Cloud Storage for file exchange."
        )
