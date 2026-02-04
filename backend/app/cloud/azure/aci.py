"""Azure Container Instances provider implementation."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.containerinstance import ContainerInstanceManagementClient
from azure.mgmt.containerinstance.models import (
    Container,
    ContainerGroup,
    ContainerGroupNetworkProtocol,
    ContainerPort,
    EnvironmentVariable,
    IpAddress,
    OperatingSystemTypes,
    Port,
    ResourceRequests,
    ResourceRequirements,
)
from azure.core.credentials import AccessToken
from azure.core.exceptions import ResourceNotFoundError

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


class StaticTokenCredential:
    """Simple credential wrapper for Azure SDK using a static access token."""

    def __init__(self, access_token: str):
        self._token = access_token

    def get_token(self, *scopes, **kwargs) -> AccessToken:
        # Return the token with a 1-hour expiry (token is already valid)
        return AccessToken(self._token, int(time.time()) + 3600)


class AzureACIProvider(VMProvider):
    """Azure Container Instances implementation of VMProvider.

    Uses Azure Container Instances to run agent containers instead of VMs.
    This provides:
    - Serverless container execution
    - Pay-per-second pricing
    - No infrastructure management
    - VNet integration for network isolation

    Each agent runs as a Container Group with a single container.
    """

    # Default container image for openclaw agents
    DEFAULT_AGENT_IMAGE = "{registry}.azurecr.io/zerg-rush-agent:latest"

    def __init__(self, user_credentials: UserCredentials | None = None):
        """Initialize the Azure Container Instances provider.

        Args:
            user_credentials: Optional user OAuth credentials. If provided,
                these will be used instead of DefaultAzureCredential.
        """
        settings = get_settings()
        self.location = settings.azure_location

        # VNet settings for network isolation
        self.vnet_name = getattr(settings, "azure_vnet_name", None)
        self.subnet_name = getattr(settings, "azure_subnet_name", None)

        # Container registry
        self.container_registry = getattr(
            settings, "azure_container_registry", "zergrush"
        )

        # Default agent container image
        self.default_image = getattr(
            settings,
            "agent_container_image",
            self.DEFAULT_AGENT_IMAGE.format(registry=self.container_registry),
        )

        if user_credentials:
            # Use user OAuth credentials
            self.credential = StaticTokenCredential(user_credentials.access_token)
            self.subscription_id = user_credentials.subscription_id or settings.azure_subscription_id
            self.resource_group = user_credentials.resource_group or settings.azure_resource_group
        else:
            # Fall back to DefaultAzureCredential (for system operations)
            self.credential = DefaultAzureCredential()
            self.subscription_id = settings.azure_subscription_id
            self.resource_group = settings.azure_resource_group

        self.client = ContainerInstanceManagementClient(
            self.credential, self.subscription_id
        )

    def _map_status(self, provisioning_state: str, instance_state: str | None) -> VMStatus:
        """Map ACI states to VMStatus."""
        state_map = {
            "Creating": VMStatus.CREATING,
            "Succeeded": VMStatus.RUNNING,
            "Running": VMStatus.RUNNING,
            "Stopped": VMStatus.STOPPED,
            "Failed": VMStatus.ERROR,
            "Deleting": VMStatus.DELETING,
            "Pending": VMStatus.CREATING,
        }

        # Check instance state first (more accurate for running containers)
        if instance_state:
            return state_map.get(instance_state, VMStatus.CREATING)

        return state_map.get(provisioning_state, VMStatus.CREATING)

    def _get_container_image(self, platform_type: str) -> str:
        """Get the container image for a platform type."""
        platform_images = {
            "openclaw": self.default_image,
        }
        return platform_images.get(platform_type, self.default_image)

    def _size_to_resources(self, size: str) -> tuple[float, float]:
        """Convert VM size string to ACI resource requests.

        Returns (cpu, memory_in_gb)
        """
        size_map = {
            # Small instances
            "e2-micro": (0.5, 0.5),
            "e2-small": (1.0, 1.0),
            "e2-medium": (2.0, 2.0),
            # Standard instances
            "e2-standard-2": (2.0, 4.0),
            "e2-standard-4": (4.0, 8.0),
            # High memory
            "e2-highmem-2": (2.0, 8.0),
            "e2-highmem-4": (4.0, 16.0),
            # ACI specific sizes
            "aci-small": (1.0, 1.0),
            "aci-medium": (2.0, 2.0),
            "aci-large": (4.0, 4.0),
        }
        return size_map.get(size, (1.0, 1.0))

    def _sanitize_name(self, name: str) -> str:
        """Sanitize container group name for Azure requirements.

        Azure container group names must be lowercase, start with letter,
        contain only letters, numbers, and hyphens.
        """
        sanitized = name.lower().replace("_", "-")
        # Ensure it starts with a letter
        if sanitized and not sanitized[0].isalpha():
            sanitized = "zr-" + sanitized
        return sanitized[:63]

    async def create_vm(
        self, config: VMConfig, session: Session | None = None
    ) -> VMInstance:
        """Create a new Azure Container Instance for the agent."""
        with FunctionTrace(
            session,
            "Creating Azure Container Instance",
            name=config.name,
            size=config.size,
            agent_id=config.agent_id,
        ) as trace:
            cpu, memory_gb = self._size_to_resources(config.size)
            container_group_name = self._sanitize_name(config.name)

            # Build environment variables
            env_vars = [
                EnvironmentVariable(name="AGENT_ID", value=config.agent_id),
                EnvironmentVariable(name="USER_ID", value=config.user_id),
                EnvironmentVariable(name="GATEWAY_PORT", value="8080"),
            ]

            # Add any custom labels as env vars
            if config.labels:
                for key, value in config.labels.items():
                    env_vars.append(
                        EnvironmentVariable(
                            name=f"LABEL_{key.upper().replace('-', '_')}",
                            value=value,
                        )
                    )

            # Build container configuration
            container = Container(
                name="agent",
                image=self._get_container_image(
                    config.labels.get("platform_type", "openclaw") if config.labels else "openclaw"
                ),
                resources=ResourceRequirements(
                    requests=ResourceRequests(cpu=cpu, memory_in_gb=memory_gb)
                ),
                ports=[ContainerPort(port=8080)],
                environment_variables=env_vars,
            )

            # Build container group - use private IP only for security
            container_group = ContainerGroup(
                location=self.location,
                containers=[container],
                os_type=OperatingSystemTypes.LINUX,
                restart_policy="Always",
                ip_address=IpAddress(
                    ports=[Port(protocol=ContainerGroupNetworkProtocol.TCP, port=8080)],
                    type="Private" if self.vnet_name else "Public",
                ),
                tags={
                    "zerg-rush": "agent",
                    "user-id": config.user_id.replace("-", "")[:63],
                    "agent-id": config.agent_id.replace("-", "")[:63],
                },
            )

            # Add VNet configuration if available
            if self.vnet_name and self.subnet_name:
                from azure.mgmt.containerinstance.models import (
                    ContainerGroupSubnetId,
                )

                subnet_id = (
                    f"/subscriptions/{self.subscription_id}"
                    f"/resourceGroups/{self.resource_group}"
                    f"/providers/Microsoft.Network/virtualNetworks/{self.vnet_name}"
                    f"/subnets/{self.subnet_name}"
                )
                container_group.subnet_ids = [
                    ContainerGroupSubnetId(id=subnet_id)
                ]
                # Remove IP address when using subnet (handled by VNet)
                container_group.ip_address = None

            # Create the container group (run in thread pool to avoid blocking event loop)
            trace.log("Sending create request to Azure...")
            poller = await asyncio.to_thread(
                self.client.container_groups.begin_create_or_update,
                self.resource_group,
                container_group_name,
                container_group,
            )

            # Wait for creation to complete
            trace.log("Waiting for container provisioning...")
            await asyncio.to_thread(poller.result)

            trace.log("Azure Container Instance created", name=container_group_name)

            return await self.get_vm_status(container_group_name, session=session)

    async def delete_vm(self, vm_id: str, session: Session | None = None) -> None:
        """Delete an Azure Container Instance."""
        with FunctionTrace(session, "Deleting Azure Container Instance", vm_id=vm_id) as trace:
            container_group_name = self._sanitize_name(vm_id)

            trace.log("Sending delete request to Azure...")
            poller = await asyncio.to_thread(
                self.client.container_groups.begin_delete,
                self.resource_group,
                container_group_name,
            )
            trace.log("Waiting for container termination...")
            await asyncio.to_thread(poller.result)
            trace.log("Azure Container Instance deleted", vm_id=vm_id)

    async def start_vm(self, vm_id: str, session: Session | None = None) -> None:
        """Start a stopped Azure Container Instance."""
        with FunctionTrace(session, "Starting Azure Container Instance", vm_id=vm_id) as trace:
            container_group_name = self._sanitize_name(vm_id)

            trace.log("Sending start request to Azure...")
            poller = await asyncio.to_thread(
                self.client.container_groups.begin_start,
                self.resource_group,
                container_group_name,
            )
            trace.log("Waiting for container to start...")
            await asyncio.to_thread(poller.result)
            trace.log("Azure Container Instance started", vm_id=vm_id)

    async def stop_vm(self, vm_id: str, session: Session | None = None) -> None:
        """Stop a running Azure Container Instance."""
        with FunctionTrace(session, "Stopping Azure Container Instance", vm_id=vm_id) as trace:
            container_group_name = self._sanitize_name(vm_id)

            trace.log("Sending stop request to Azure...")
            await asyncio.to_thread(
                self.client.container_groups.stop,
                self.resource_group,
                container_group_name,
            )
            trace.log("Azure Container Instance stopped", vm_id=vm_id)

    async def get_vm_status(
        self, vm_id: str, session: Session | None = None
    ) -> VMInstance:
        """Get current status of an Azure Container Instance."""
        container_group_name = self._sanitize_name(vm_id)

        try:
            container_group = await asyncio.to_thread(
                self.client.container_groups.get,
                self.resource_group,
                container_group_name,
            )
        except ResourceNotFoundError:
            return VMInstance(
                vm_id=vm_id,
                name=vm_id,
                status=VMStatus.DELETED,
                internal_ip=None,
                external_ip=None,
                created_at=datetime.now(timezone.utc),
                zone=self.location,
            )

        # Get IP address
        internal_ip = None
        if container_group.ip_address:
            internal_ip = container_group.ip_address.ip

        # Get instance state from first container
        instance_state = None
        if container_group.containers and container_group.containers[0].instance_view:
            current_state = container_group.containers[0].instance_view.current_state
            if current_state:
                instance_state = current_state.state

        # Map status
        status = self._map_status(
            container_group.provisioning_state or "Unknown",
            instance_state,
        )

        # Build URL for internal communication
        if internal_ip:
            service_url = f"http://{internal_ip}:8080"
        else:
            service_url = None

        return VMInstance(
            vm_id=vm_id,
            name=container_group_name,
            status=status,
            internal_ip=service_url,  # Use full URL like Cloud Run
            external_ip=None,  # No external IP for security
            created_at=datetime.now(timezone.utc),  # ACI doesn't expose creation time easily
            zone=self.location,
            metadata={
                "provisioning_state": container_group.provisioning_state,
                "instance_state": instance_state,
                "tags": dict(container_group.tags) if container_group.tags else {},
            },
        )

    async def run_command(
        self,
        vm_id: str,
        command: str,
        timeout: int = 300,
        session: Session | None = None,
    ) -> CommandResult:
        """Run a command in an Azure Container Instance.

        Uses ACI exec functionality.
        """
        container_group_name = self._sanitize_name(vm_id)

        from azure.mgmt.containerinstance.models import ContainerExecRequest

        exec_request = ContainerExecRequest(
            command=command,
            terminal_size={"rows": 24, "cols": 80},
        )

        result = self.client.containers.execute_command(
            self.resource_group,
            container_group_name,
            "agent",  # Container name
            exec_request,
        )

        # Note: ACI exec returns a websocket URL for interactive sessions
        # For non-interactive commands, we'd need a different approach
        raise NotImplementedError(
            "ACI command execution requires websocket connection. "
            "Use the agent's API endpoint for communication instead."
        )

    async def upload_file(
        self,
        vm_id: str,
        local_content: bytes,
        remote_path: str,
        session: Session | None = None,
    ) -> None:
        """Upload a file to an Azure Container Instance."""
        raise NotImplementedError(
            "ACI containers should use Azure Blob Storage for file exchange."
        )

    async def download_file(
        self, vm_id: str, remote_path: str, session: Session | None = None
    ) -> bytes:
        """Download a file from an Azure Container Instance."""
        raise NotImplementedError(
            "ACI containers should use Azure Blob Storage for file exchange."
        )

    async def list_files(
        self, vm_id: str, path: str, session: Session | None = None
    ) -> list[dict[str, Any]]:
        """List files in an Azure Container Instance."""
        raise NotImplementedError(
            "ACI containers should use Azure Blob Storage for file exchange."
        )
