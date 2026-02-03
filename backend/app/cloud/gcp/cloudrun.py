"""GCP Cloud Run provider implementation."""

import json
from datetime import datetime, timezone
from typing import Any

from google.cloud import run_v2
from google.api_core.exceptions import NotFound
from google.protobuf import duration_pb2
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
from app.tracing import Session


class GCPCloudRunProvider(VMProvider):
    """GCP Cloud Run implementation of VMProvider.

    Uses Cloud Run services to run agent containers instead of VMs.
    This provides:
    - Automatic scaling
    - Pay-per-use pricing
    - No infrastructure management
    - Built-in load balancing

    Each agent runs as a Cloud Run service with min_instances=1
    to ensure it's always available.
    """

    # Default container image for openclaw agents
    DEFAULT_AGENT_IMAGE = "gcr.io/{project}/zerg-rush-agent:latest"

    def __init__(self, user_credentials: UserCredentials | None = None):
        """Initialize the GCP Cloud Run provider.

        Args:
            user_credentials: Optional user OAuth credentials. If provided,
                these will be used instead of application default credentials.
        """
        settings = get_settings()
        self.region = settings.gcp_region

        # Cloud Run VPC connector for internal networking
        self.vpc_connector = getattr(settings, 'gcp_vpc_connector', None)

        if user_credentials:
            # Use user OAuth credentials
            credentials = OAuthCredentials(token=user_credentials.access_token)
            self.project_id = user_credentials.project_id or settings.gcp_project_id
            self.services_client = run_v2.ServicesClient(credentials=credentials)
            self.revisions_client = run_v2.RevisionsClient(credentials=credentials)
        else:
            # Fall back to application default credentials (for system operations)
            self.project_id = settings.gcp_project_id
            self.services_client = run_v2.ServicesClient()
            self.revisions_client = run_v2.RevisionsClient()

        # Default agent container image
        self.default_image = getattr(
            settings,
            'agent_container_image',
            self.DEFAULT_AGENT_IMAGE.format(project=self.project_id)
        )

    def _get_parent(self) -> str:
        """Get the parent resource path."""
        return f"projects/{self.project_id}/locations/{self.region}"

    def _get_service_name(self, service_id: str) -> str:
        """Get the full service resource name."""
        return f"{self._get_parent()}/services/{service_id}"

    def _map_status(self, conditions: list) -> VMStatus:
        """Map Cloud Run conditions to VMStatus."""
        if not conditions:
            return VMStatus.CREATING

        # Check the Ready condition
        for condition in conditions:
            if condition.type == "Ready":
                if condition.state == run_v2.Condition.State.CONDITION_SUCCEEDED:
                    return VMStatus.RUNNING
                elif condition.state == run_v2.Condition.State.CONDITION_FAILED:
                    return VMStatus.ERROR
                else:
                    return VMStatus.CREATING

        return VMStatus.CREATING

    def _get_container_image(self, platform_type: str) -> str:
        """Get the container image for a platform type."""
        # In the future, support multiple platform images
        platform_images = {
            "openclaw": self.default_image,
        }
        return platform_images.get(platform_type, self.default_image)

    def _size_to_resources(self, size: str) -> tuple[str, str]:
        """Convert VM size string to Cloud Run resource limits.

        Returns (cpu_limit, memory_limit)
        """
        # Map common VM sizes to Cloud Run resources
        size_map = {
            # Small instances
            "e2-micro": ("1", "512Mi"),
            "e2-small": ("1", "1Gi"),
            "e2-medium": ("2", "2Gi"),
            # Standard instances
            "e2-standard-2": ("2", "4Gi"),
            "e2-standard-4": ("4", "8Gi"),
            # High memory
            "e2-highmem-2": ("2", "8Gi"),
            "e2-highmem-4": ("4", "16Gi"),
            # Cloud Run specific sizes
            "cloudrun-small": ("1", "1Gi"),
            "cloudrun-medium": ("2", "2Gi"),
            "cloudrun-large": ("4", "4Gi"),
        }
        return size_map.get(size, ("1", "1Gi"))

    async def create_vm(
        self, config: VMConfig, session: Session | None = None
    ) -> VMInstance:
        """Create a new Cloud Run service for the agent."""
        if session:
            session.log(
                "Creating Cloud Run service",
                name=config.name,
                size=config.size,
                agent_id=config.agent_id,
            )

        cpu_limit, memory_limit = self._size_to_resources(config.size)

        # Build environment variables
        env_vars = [
            run_v2.EnvVar(name="AGENT_ID", value=config.agent_id),
            run_v2.EnvVar(name="USER_ID", value=config.user_id),
            run_v2.EnvVar(name="GATEWAY_PORT", value="8080"),  # Cloud Run requires 8080
        ]

        # Add any custom labels as env vars
        if config.labels:
            for key, value in config.labels.items():
                env_vars.append(run_v2.EnvVar(
                    name=f"LABEL_{key.upper().replace('-', '_')}",
                    value=value
                ))

        # Build container configuration
        container = run_v2.Container(
            image=self._get_container_image(config.labels.get("platform_type", "openclaw") if config.labels else "openclaw"),
            ports=[run_v2.ContainerPort(container_port=8080)],
            resources=run_v2.ResourceRequirements(
                limits={"cpu": cpu_limit, "memory": memory_limit},
            ),
            env=env_vars,
        )

        # Build service template
        template = run_v2.RevisionTemplate(
            containers=[container],
            scaling=run_v2.RevisionScaling(
                min_instance_count=1,  # Always keep one instance running
                max_instance_count=1,  # Single instance per agent
            ),
            timeout=duration_pb2.Duration(seconds=3600),  # 1 hour timeout
            service_account=f"zerg-rush-agent@{self.project_id}.iam.gserviceaccount.com",
        )

        # Add VPC connector for internal networking if configured
        if self.vpc_connector:
            template.vpc_access = run_v2.VpcAccess(
                connector=self.vpc_connector,
                egress=run_v2.VpcAccess.VpcEgress.ALL_TRAFFIC,
            )

        # Build the service
        service = run_v2.Service(
            template=template,
            labels={
                "zerg-rush": "agent",
                "user-id": config.user_id.replace("-", "")[:63],
                "agent-id": config.agent_id.replace("-", "")[:63],
            },
            ingress=run_v2.IngressTraffic.INGRESS_TRAFFIC_INTERNAL_ONLY,  # Internal only for security
        )

        # Create the service
        request = run_v2.CreateServiceRequest(
            parent=self._get_parent(),
            service=service,
            service_id=config.name,
        )

        try:
            operation = self.services_client.create_service(request=request)

            # Wait for the operation to complete
            result = operation.result()

            if session:
                session.log("Cloud Run service created", name=config.name)

            return await self.get_vm_status(config.name, session=session)
        except Exception as e:
            if session:
                session.log(
                    "Cloud Run service creation failed",
                    name=config.name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def delete_vm(self, vm_id: str, session: Session | None = None) -> None:
        """Delete a Cloud Run service."""
        if session:
            session.log("Deleting Cloud Run service", vm_id=vm_id)

        try:
            request = run_v2.DeleteServiceRequest(
                name=self._get_service_name(vm_id),
            )

            operation = self.services_client.delete_service(request=request)
            operation.result()  # Wait for deletion

            if session:
                session.log("Cloud Run service deleted", vm_id=vm_id)
        except Exception as e:
            if session:
                session.log(
                    "Cloud Run service deletion failed",
                    vm_id=vm_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def start_vm(self, vm_id: str, session: Session | None = None) -> None:
        """Start a Cloud Run service by setting min_instances to 1.

        Cloud Run services are always "running" in a sense, but we can
        control whether instances are kept warm by adjusting min_instances.
        """
        if session:
            session.log("Starting Cloud Run service", vm_id=vm_id)

        try:
            # Get current service
            service = self.services_client.get_service(
                name=self._get_service_name(vm_id)
            )

            # Update scaling to ensure at least one instance
            service.template.scaling.min_instance_count = 1

            request = run_v2.UpdateServiceRequest(service=service)
            operation = self.services_client.update_service(request=request)
            operation.result()

            if session:
                session.log("Cloud Run service started", vm_id=vm_id)
        except Exception as e:
            if session:
                session.log(
                    "Cloud Run service start failed",
                    vm_id=vm_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def stop_vm(self, vm_id: str, session: Session | None = None) -> None:
        """Stop a Cloud Run service by setting min_instances to 0.

        This allows the service to scale to zero, effectively "stopping" it
        while keeping the configuration intact.
        """
        if session:
            session.log("Stopping Cloud Run service", vm_id=vm_id)

        try:
            # Get current service
            service = self.services_client.get_service(
                name=self._get_service_name(vm_id)
            )

            # Update scaling to allow scale to zero
            service.template.scaling.min_instance_count = 0

            request = run_v2.UpdateServiceRequest(service=service)
            operation = self.services_client.update_service(request=request)
            operation.result()

            if session:
                session.log("Cloud Run service stopped", vm_id=vm_id)
        except Exception as e:
            if session:
                session.log(
                    "Cloud Run service stop failed",
                    vm_id=vm_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            raise

    async def get_vm_status(
        self, vm_id: str, session: Session | None = None
    ) -> VMInstance:
        """Get current status of a Cloud Run service."""
        try:
            service = self.services_client.get_service(
                name=self._get_service_name(vm_id)
            )
        except NotFound:
            return VMInstance(
                vm_id=vm_id,
                name=vm_id,
                status=VMStatus.DELETED,
                internal_ip=None,
                external_ip=None,
                created_at=datetime.now(timezone.utc),
                zone=self.region,
            )

        # Get the service URL (this is the internal URL for communication)
        service_url = service.uri

        # Determine status from conditions
        status = self._map_status(list(service.conditions))

        # Check if service is scaled to zero (stopped)
        if service.template.scaling.min_instance_count == 0:
            status = VMStatus.STOPPED

        # Parse creation time
        created_at = datetime.now(timezone.utc)
        if service.create_time:
            created_at = service.create_time

        return VMInstance(
            vm_id=vm_id,
            name=vm_id,
            status=status,
            internal_ip=service_url,  # Use service URL as the "internal IP"
            external_ip=None,  # No external IP for security
            created_at=created_at,
            zone=self.region,
            metadata={
                "uri": service_url,
                "generation": service.generation,
                "labels": dict(service.labels) if service.labels else {},
            },
        )

    async def run_command(
        self,
        vm_id: str,
        command: str,
        timeout: int = 300,
        session: Session | None = None,
    ) -> CommandResult:
        """Run a command in a Cloud Run container.

        Uses Cloud Run Jobs to execute one-off commands.
        """
        # For Cloud Run, we'd typically use Cloud Run Jobs for one-off commands
        # or exec into the container (requires additional setup)
        raise NotImplementedError(
            "Direct command execution in Cloud Run requires Cloud Run Jobs. "
            "Use the agent's API endpoint for communication instead."
        )

    async def upload_file(
        self,
        vm_id: str,
        local_content: bytes,
        remote_path: str,
        session: Session | None = None,
    ) -> None:
        """Upload a file to a Cloud Run container.

        Cloud Run containers are stateless, so files should be stored
        in Cloud Storage and accessed via mounted volumes or API.
        """
        raise NotImplementedError(
            "Cloud Run containers are stateless. "
            "Use Cloud Storage for file exchange."
        )

    async def download_file(
        self, vm_id: str, remote_path: str, session: Session | None = None
    ) -> bytes:
        """Download a file from a Cloud Run container."""
        raise NotImplementedError(
            "Cloud Run containers are stateless. "
            "Use Cloud Storage for file exchange."
        )

    async def list_files(
        self, vm_id: str, path: str, session: Session | None = None
    ) -> list[dict[str, Any]]:
        """List files in a Cloud Run container."""
        raise NotImplementedError(
            "Cloud Run containers are stateless. "
            "Use Cloud Storage for file exchange."
        )
