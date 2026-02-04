"""Agent management routes."""

import asyncio
import json
from datetime import datetime
from typing import Annotated, AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents import get_platform
from app.api.dependencies import (
    CurrentUser,
    DbSession,
    log_action,
    get_client_ip,
    UserCloudProviders,
    StreamingSession,
)
from app.cloud.factory import get_providers, CloudProviders
from app.cloud.interfaces import VMConfig, VMStatus
from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models import ActiveAgent, SavedAgent, Credential, AgentCredential
from app.tracing import ActiveSession

router = APIRouter()
settings = get_settings()


# Request/Response models
class CreateAgentRequest(BaseModel):
    """Request to create a new agent."""

    name: str = Field(..., min_length=1, max_length=255)
    platform_type: str = Field(default="openclaw")
    vm_size: str = Field(default=None)
    template_id: str | None = None
    credential_ids: list[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    """Agent information response."""

    id: str
    name: str
    vm_id: str
    vm_size: str
    vm_status: str
    vm_internal_ip: str | None
    vm_external_ip: str | None
    vm_zone: str | None
    cloud_provider: str
    bucket_id: str
    current_task: str | None
    platform_type: str
    platform_version: str | None
    template_id: str | None
    gateway_port: int
    created_at: datetime
    updated_at: datetime
    # Computed fields for UI links
    cloud_console_url: str | None = None
    ssh_url: str | None = None
    ssh_command: str | None = None

    class Config:
        from_attributes = True


def _get_vm_name(agent_id: str) -> str:
    """Reconstruct VM name from agent ID."""
    return f"zr-agent-{agent_id[:8]}"


def _compute_cloud_urls(agent: "ActiveAgent") -> dict[str, str | None]:
    """Compute cloud console and SSH URLs for an agent."""
    cloud_console_url = None
    ssh_url = None
    ssh_command = None

    vm_name = _get_vm_name(agent.id)

    if agent.cloud_provider == "gcp":
        project_id = settings.gcp_project_id
        if project_id and agent.vm_zone:
            if settings.gcp_compute_type == "cloudrun":
                # Cloud Run service URL
                region = settings.gcp_region
                cloud_console_url = (
                    f"https://console.cloud.google.com/run/detail/{region}/{vm_name}"
                    f"?project={project_id}"
                )
                # No SSH for Cloud Run
            else:
                # GCE instance URL
                cloud_console_url = (
                    f"https://console.cloud.google.com/compute/instancesDetail"
                    f"/zones/{agent.vm_zone}/instances/{vm_name}?project={project_id}"
                )
                # GCE web SSH URL
                ssh_url = (
                    f"https://console.cloud.google.com/compute/instancesDetail"
                    f"/zones/{agent.vm_zone}/instances/{vm_name}"
                    f"?project={project_id}&authuser=0#sshWeb"
                )
    elif agent.cloud_provider == "azure":
        subscription_id = settings.azure_subscription_id
        resource_group = settings.azure_resource_group
        tenant_id = settings.azure_tenant_id
        if subscription_id and resource_group:
            # Azure Portal URL for container instance
            cloud_console_url = (
                f"https://portal.azure.com/#@{tenant_id}/resource"
                f"/subscriptions/{subscription_id}"
                f"/resourceGroups/{resource_group}"
                f"/providers/Microsoft.ContainerInstance/containerGroups/{agent.vm_id}"
            )
            # Azure CLI command for exec into container
            ssh_command = (
                f"az container exec --resource-group {resource_group} "
                f"--name {agent.vm_id} --exec-command /bin/bash"
            )

    return {
        "cloud_console_url": cloud_console_url,
        "ssh_url": ssh_url,
        "ssh_command": ssh_command,
    }


def _agent_to_response(agent: "ActiveAgent") -> AgentResponse:
    """Convert an ActiveAgent to AgentResponse with computed URLs."""
    urls = _compute_cloud_urls(agent)
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        vm_id=agent.vm_id,
        vm_size=agent.vm_size,
        vm_status=agent.vm_status,
        vm_internal_ip=agent.vm_internal_ip,
        vm_external_ip=agent.vm_external_ip,
        vm_zone=agent.vm_zone,
        cloud_provider=agent.cloud_provider,
        bucket_id=agent.bucket_id,
        current_task=agent.current_task,
        platform_type=agent.platform_type,
        platform_version=agent.platform_version,
        template_id=agent.template_id,
        gateway_port=agent.gateway_port,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        cloud_console_url=urls["cloud_console_url"],
        ssh_url=urls["ssh_url"],
        ssh_command=urls["ssh_command"],
    )


class AgentListResponse(BaseModel):
    """List of agents response."""

    agents: list[AgentResponse]
    total: int


class ChatRequest(BaseModel):
    """Request to send a chat message to an agent."""

    message: str


class ChatResponse(BaseModel):
    """Response from agent chat."""

    response: str


# Routes
@router.get("", response_model=AgentListResponse)
async def list_agents(
    current_user: CurrentUser,
    db: DbSession,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AgentListResponse:
    """List all active agents for the current user."""
    # Get total count
    count_result = await db.execute(
        select(ActiveAgent).where(ActiveAgent.user_id == current_user.id)
    )
    total = len(count_result.scalars().all())

    # Get paginated agents
    result = await db.execute(
        select(ActiveAgent)
        .where(ActiveAgent.user_id == current_user.id)
        .order_by(ActiveAgent.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    agents = result.scalars().all()

    return AgentListResponse(
        agents=[_agent_to_response(a) for a in agents],
        total=total,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    current_user: CurrentUser,
    db: DbSession,
    agent_id: str,
) -> AgentResponse:
    """Get a specific agent by ID."""
    result = await db.execute(
        select(ActiveAgent).where(
            ActiveAgent.id == agent_id,
            ActiveAgent.user_id == current_user.id,
        )
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    return _agent_to_response(agent)


@router.get("/{agent_id}/status", response_model=AgentResponse)
async def get_agent_status(
    current_user: CurrentUser,
    db: DbSession,
    providers: UserCloudProviders,
    agent_id: str,
) -> AgentResponse:
    """Get the current status of an agent (refreshes from cloud)."""

    result = await db.execute(
        select(ActiveAgent).where(
            ActiveAgent.id == agent_id,
            ActiveAgent.user_id == current_user.id,
        )
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Refresh status from cloud
    try:
        vm_instance = await providers.vm.get_vm_status(agent.vm_id)
        agent.vm_status = vm_instance.status.value
        agent.vm_internal_ip = vm_instance.internal_ip
        agent.vm_external_ip = vm_instance.external_ip
        await db.commit()
        await db.refresh(agent)
    except Exception as e:
        # If VM is not found, mark as error
        agent.vm_status = VMStatus.ERROR.value
        await db.commit()

    return _agent_to_response(agent)


@router.post("/{agent_id}/archive", status_code=status.HTTP_201_CREATED)
async def archive_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    agent_id: str,
    name: Annotated[str | None, Query()] = None,
) -> dict:
    """Archive the current state of an agent as a saved template."""
    result = await db.execute(
        select(ActiveAgent).where(
            ActiveAgent.id == agent_id,
            ActiveAgent.user_id == current_user.id,
        )
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Create saved agent
    saved_name = name or f"{agent.name} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    saved_agent = SavedAgent(
        id=str(uuid4()),
        user_id=current_user.id,
        name=saved_name,
        platform_type=agent.platform_type,
        source_agent_id=agent.id,
        config_snapshot={
            "vm_size": agent.vm_size,
            "platform_version": agent.platform_version,
        },
    )
    db.add(saved_agent)

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="agent.archive",
        target_type="agent",
        target_id=agent_id,
        details={"saved_agent_id": saved_agent.id, "name": saved_name},
        ip_address=get_client_ip(request),
    )

    await db.commit()

    return {"id": saved_agent.id, "name": saved_name}


@router.post("/{agent_id}/chat", response_model=ChatResponse)
async def chat_with_agent(
    current_user: CurrentUser,
    db: DbSession,
    agent_id: str,
    body: ChatRequest,
) -> ChatResponse:
    """Send a chat message to an agent (proxied through backend)."""
    import httpx

    result = await db.execute(
        select(ActiveAgent).where(
            ActiveAgent.id == agent_id,
            ActiveAgent.user_id == current_user.id,
        )
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    if agent.vm_status != VMStatus.RUNNING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent is not running (status: {agent.vm_status})",
        )

    if not agent.vm_internal_ip:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent has no internal IP address or URL",
        )

    # Build gateway URL - handle both Cloud Run URLs and traditional IPs
    # Cloud Run URLs are full URLs (https://...), while GCE uses IPs
    if agent.vm_internal_ip.startswith("http"):
        # Cloud Run: URL is already complete, just append the API path
        gateway_url = f"{agent.vm_internal_ip}/api/chat"
    else:
        # GCE: Construct URL from IP and port
        gateway_url = f"http://{agent.vm_internal_ip}:{agent.gateway_port}/api/chat"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                gateway_url,
                json={"message": body.message},
            )
            response.raise_for_status()
            data = response.json()
            return ChatResponse(response=data.get("response", ""))
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Agent did not respond in time",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent returned error: {e.response.status_code}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to communicate with agent: {str(e)}",
        )


# =============================================================================
# Streaming endpoints for long-running operations
# =============================================================================


async def _stream_events(
    session: ActiveSession,
    operation: asyncio.Future,
) -> AsyncGenerator[str, None]:
    """Stream events from a session as Server-Sent Events (SSE).

    Args:
        session: The streaming session to read events from.
        operation: The async operation running in the background.
    """
    try:
        async for event in session.stream_events():
            yield f"data: {json.dumps(event.to_dict())}\n\n"
    except asyncio.CancelledError:
        # Client disconnected
        operation.cancel()
        raise
    except Exception as e:
        # Send error event
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@router.post("/stream", response_class=StreamingResponse)
async def create_agent_streaming(
    request: Request,
    current_user: CurrentUser,
    providers: UserCloudProviders,
    body: CreateAgentRequest,
    session: StreamingSession,
) -> StreamingResponse:
    """Create a new agent with streaming progress updates.

    Returns Server-Sent Events (SSE) with progress updates during creation.
    The final event will be either:
    - type: "complete" with the created agent data
    - type: "error" with error details
    """
    session.set_user(current_user)
    # Capture values needed in background task
    user_id = current_user.id
    client_ip = get_client_ip(request)

    async def run_creation() -> None:
        """Run the agent creation and emit events."""
        # Use default VM size if not specified
        vm_size = body.vm_size or settings.default_vm_size

        # Generate unique identifiers
        agent_id = str(uuid4())
        vm_name = f"zr-agent-{agent_id[:8]}"
        bucket_name = f"agent-{agent_id[:8]}"

        # Create a new database session for this background task
        async with AsyncSessionLocal() as db:
            try:
                session.log("Starting agent creation", name=body.name)

                # Validate template if specified
                template = None
                if body.template_id:
                    with session.span("Validate template"):
                        result = await db.execute(
                            select(SavedAgent).where(
                                SavedAgent.id == body.template_id,
                                SavedAgent.user_id == user_id,
                            )
                        )
                        template = result.scalar_one_or_none()
                        if not template:
                            raise ValueError("Template not found")
                        session.log("Template validated", template_id=body.template_id)

                # Validate credentials
                if body.credential_ids:
                    with session.span("Validate credentials"):
                        result = await db.execute(
                            select(Credential).where(
                                Credential.id.in_(body.credential_ids),
                                Credential.user_id == user_id,
                            )
                        )
                        credentials = result.scalars().all()
                        if len(credentials) != len(body.credential_ids):
                            raise ValueError("One or more credentials not found")
                        session.log("Credentials validated", count=len(credentials))

                # Create storage bucket
                bucket_id = None
                with session.span("Create storage bucket"):
                    try:
                        session.log("Provisioning cloud storage...")
                        bucket_id = await providers.storage.create_bucket(
                            name=bucket_name,
                            user_id=user_id,
                            session=session,
                        )
                        session.log("Storage bucket created", bucket_id=bucket_id)
                    except Exception as e:
                        raise ValueError(f"Failed to create storage bucket: {str(e)}")

                # Create VM
                vm_instance = None
                with session.span("Create VM"):
                    try:
                        session.log("Provisioning virtual machine...")
                        vm_config = VMConfig(
                            name=vm_name,
                            size=vm_size,
                            image="default",
                            user_id=user_id,
                            agent_id=agent_id,
                            startup_script=get_platform(body.platform_type).get_startup_script(current_user),
                        )
                        vm_instance = await providers.vm.create_vm(vm_config, session=session)
                        session.log("VM created successfully", vm_id=vm_instance.vm_id)
                    except Exception as e:
                        # Clean up bucket on failure
                        session.log("VM creation failed, cleaning up bucket", error=str(e))
                        if bucket_id:
                            try:
                                await providers.storage.delete_bucket(bucket_id, session=session)
                            except Exception:
                                pass
                        raise ValueError(f"Failed to create VM: {str(e)}")

                # Create agent record
                with session.span("Save agent record"):
                    agent = ActiveAgent(
                        id=agent_id,
                        user_id=user_id,
                        name=body.name,
                        vm_id=vm_instance.vm_id,
                        vm_size=vm_size,
                        vm_status=vm_instance.status.value,
                        vm_internal_ip=vm_instance.internal_ip,
                        vm_external_ip=vm_instance.external_ip,
                        vm_zone=vm_instance.zone,
                        cloud_provider=settings.cloud_provider,
                        bucket_id=bucket_id,
                        platform_type=body.platform_type,
                        template_id=body.template_id,
                    )
                    db.add(agent)

                    # Grant credentials to agent
                    for cred_id in body.credential_ids:
                        agent_cred = AgentCredential(
                            agent_id=agent_id,
                            credential_id=cred_id,
                        )
                        db.add(agent_cred)

                    # Log action
                    await log_action(
                        db=db,
                        user_id=user_id,
                        action_type="agent.create",
                        target_type="agent",
                        target_id=agent_id,
                        details={
                            "name": body.name,
                            "platform_type": body.platform_type,
                            "vm_size": vm_size,
                            "template_id": body.template_id,
                        },
                        ip_address=client_ip,
                    )

                    await db.commit()
                    await db.refresh(agent)
                    session.log("Agent record saved")

                # Emit completion event with agent data
                agent_response = _agent_to_response(agent)
                session.emit_completion(
                    message="Agent created successfully",
                    data={
                        "agent": {
                            "id": agent_response.id,
                            "name": agent_response.name,
                            "vm_id": agent_response.vm_id,
                            "vm_size": agent_response.vm_size,
                            "vm_status": agent_response.vm_status,
                            "vm_internal_ip": agent_response.vm_internal_ip,
                            "vm_external_ip": agent_response.vm_external_ip,
                            "vm_zone": agent_response.vm_zone,
                            "cloud_provider": agent_response.cloud_provider,
                            "bucket_id": agent_response.bucket_id,
                            "current_task": agent_response.current_task,
                            "platform_type": agent_response.platform_type,
                            "platform_version": agent_response.platform_version,
                            "template_id": agent_response.template_id,
                            "gateway_port": agent_response.gateway_port,
                            "created_at": agent.created_at.isoformat(),
                            "updated_at": agent.updated_at.isoformat(),
                            "cloud_console_url": agent_response.cloud_console_url,
                            "ssh_url": agent_response.ssh_url,
                            "ssh_command": agent_response.ssh_command,
                        }
                    },
                )

            except Exception as e:
                await db.rollback()
                session.finish_streaming(error=str(e))

    # Start the creation task
    task = asyncio.create_task(run_creation())

    return StreamingResponse(
        _stream_events(session, task),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.delete("/{agent_id}/stream", response_class=StreamingResponse)
async def delete_agent_streaming(
    request: Request,
    current_user: CurrentUser,
    providers: UserCloudProviders,
    agent_id: str,
    session: StreamingSession,
) -> StreamingResponse:
    """Delete an agent with streaming progress updates.

    Returns Server-Sent Events (SSE) with progress updates during deletion.
    """
    session.set_user(current_user)
    # Capture values needed in background task
    user_id = current_user.id
    client_ip = get_client_ip(request)

    async def run_deletion() -> None:
        """Run the agent deletion and emit events."""
        # Create a new database session for this background task
        async with AsyncSessionLocal() as db:
            try:
                session.log("Starting agent deletion", agent_id=agent_id)

                result = await db.execute(
                    select(ActiveAgent).where(
                        ActiveAgent.id == agent_id,
                        ActiveAgent.user_id == user_id,
                    )
                )
                agent = result.scalar_one_or_none()

                if not agent:
                    raise ValueError("Agent not found")

                agent_name = agent.name

                # Delete VM
                with session.span("Delete VM"):
                    try:
                        session.log("Terminating virtual machine...")
                        await providers.vm.delete_vm(agent.vm_id, session=session)
                        session.log("VM deleted")
                    except Exception as e:
                        session.log("VM deletion failed (may already be deleted)", error=str(e))

                # Delete storage bucket
                with session.span("Delete storage bucket"):
                    try:
                        session.log("Removing storage bucket...")
                        await providers.storage.delete_bucket(agent.bucket_id, session=session)
                        session.log("Storage bucket deleted")
                    except Exception as e:
                        session.log("Bucket deletion failed (may already be deleted)", error=str(e))

                # Log action and delete from database
                with session.span("Finalize deletion"):
                    await log_action(
                        db=db,
                        user_id=user_id,
                        action_type="agent.delete",
                        target_type="agent",
                        target_id=agent_id,
                        details={"name": agent_name},
                        ip_address=client_ip,
                    )

                    await db.delete(agent)
                    await db.commit()
                    session.log("Agent record deleted")

                # Emit completion event
                session.emit_completion(
                    message="Agent deleted successfully",
                    data={"agent_id": agent_id},
                )

            except Exception as e:
                await db.rollback()
                session.finish_streaming(error=str(e))

    task = asyncio.create_task(run_deletion())

    return StreamingResponse(
        _stream_events(session, task),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{agent_id}/start/stream", response_class=StreamingResponse)
async def start_agent_streaming(
    request: Request,
    current_user: CurrentUser,
    providers: UserCloudProviders,
    agent_id: str,
    session: StreamingSession,
) -> StreamingResponse:
    """Start a stopped agent with streaming progress updates."""
    session.set_user(current_user)
    # Capture values needed in background task
    user_id = current_user.id
    client_ip = get_client_ip(request)

    async def run_start() -> None:
        # Create a new database session for this background task
        async with AsyncSessionLocal() as db:
            try:
                session.log("Starting agent", agent_id=agent_id)

                result = await db.execute(
                    select(ActiveAgent).where(
                        ActiveAgent.id == agent_id,
                        ActiveAgent.user_id == user_id,
                    )
                )
                agent = result.scalar_one_or_none()

                if not agent:
                    raise ValueError("Agent not found")

                if agent.vm_status not in [VMStatus.STOPPED.value, VMStatus.ERROR.value]:
                    raise ValueError(f"Agent cannot be started from status: {agent.vm_status}")

                with session.span("Start VM"):
                    session.log("Starting virtual machine...")
                    await providers.vm.start_vm(agent.vm_id, session=session)
                    session.log("Waiting for VM to initialize...")
                    vm_instance = await providers.vm.get_vm_status(agent.vm_id, session=session)
                    agent.vm_status = vm_instance.status.value
                    agent.vm_internal_ip = vm_instance.internal_ip
                    agent.vm_external_ip = vm_instance.external_ip
                    session.log("VM started", status=agent.vm_status)

                await log_action(
                    db=db,
                    user_id=user_id,
                    action_type="agent.start",
                    target_type="agent",
                    target_id=agent_id,
                    ip_address=client_ip,
                )

                await db.commit()
                await db.refresh(agent)

                agent_response = _agent_to_response(agent)
                session.emit_completion(
                    message="Agent started successfully",
                    data={
                        "agent": {
                            "id": agent_response.id,
                            "name": agent_response.name,
                            "vm_id": agent_response.vm_id,
                            "vm_size": agent_response.vm_size,
                            "vm_status": agent_response.vm_status,
                            "vm_internal_ip": agent_response.vm_internal_ip,
                            "vm_external_ip": agent_response.vm_external_ip,
                            "vm_zone": agent_response.vm_zone,
                            "cloud_provider": agent_response.cloud_provider,
                            "bucket_id": agent_response.bucket_id,
                            "current_task": agent_response.current_task,
                            "platform_type": agent_response.platform_type,
                            "platform_version": agent_response.platform_version,
                            "template_id": agent_response.template_id,
                            "gateway_port": agent_response.gateway_port,
                            "created_at": agent.created_at.isoformat(),
                            "updated_at": agent.updated_at.isoformat(),
                            "cloud_console_url": agent_response.cloud_console_url,
                            "ssh_url": agent_response.ssh_url,
                            "ssh_command": agent_response.ssh_command,
                        }
                    },
                )

            except Exception as e:
                await db.rollback()
                session.finish_streaming(error=str(e))

    task = asyncio.create_task(run_start())

    return StreamingResponse(
        _stream_events(session, task),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{agent_id}/stop/stream", response_class=StreamingResponse)
async def stop_agent_streaming(
    request: Request,
    current_user: CurrentUser,
    providers: UserCloudProviders,
    agent_id: str,
    session: StreamingSession,
) -> StreamingResponse:
    """Stop a running agent with streaming progress updates."""
    session.set_user(current_user)
    # Capture values needed in background task
    user_id = current_user.id
    client_ip = get_client_ip(request)

    async def run_stop() -> None:
        # Create a new database session for this background task
        async with AsyncSessionLocal() as db:
            try:
                session.log("Stopping agent", agent_id=agent_id)

                result = await db.execute(
                    select(ActiveAgent).where(
                        ActiveAgent.id == agent_id,
                        ActiveAgent.user_id == user_id,
                    )
                )
                agent = result.scalar_one_or_none()

                if not agent:
                    raise ValueError("Agent not found")

                if agent.vm_status != VMStatus.RUNNING.value:
                    raise ValueError(f"Agent cannot be stopped from status: {agent.vm_status}")

                with session.span("Stop VM"):
                    session.log("Stopping virtual machine...")
                    await providers.vm.stop_vm(agent.vm_id, session=session)
                    session.log("Waiting for VM to shut down...")
                    vm_instance = await providers.vm.get_vm_status(agent.vm_id, session=session)
                    agent.vm_status = vm_instance.status.value
                    session.log("VM stopped", status=agent.vm_status)

                await log_action(
                    db=db,
                    user_id=user_id,
                    action_type="agent.stop",
                    target_type="agent",
                    target_id=agent_id,
                    ip_address=client_ip,
                )

                await db.commit()
                await db.refresh(agent)

                agent_response = _agent_to_response(agent)
                session.emit_completion(
                    message="Agent stopped successfully",
                    data={
                        "agent": {
                            "id": agent_response.id,
                            "name": agent_response.name,
                            "vm_id": agent_response.vm_id,
                            "vm_size": agent_response.vm_size,
                            "vm_status": agent_response.vm_status,
                            "vm_internal_ip": agent_response.vm_internal_ip,
                            "vm_external_ip": agent_response.vm_external_ip,
                            "vm_zone": agent_response.vm_zone,
                            "cloud_provider": agent_response.cloud_provider,
                            "bucket_id": agent_response.bucket_id,
                            "current_task": agent_response.current_task,
                            "platform_type": agent_response.platform_type,
                            "platform_version": agent_response.platform_version,
                            "template_id": agent_response.template_id,
                            "gateway_port": agent_response.gateway_port,
                            "created_at": agent.created_at.isoformat(),
                            "updated_at": agent.updated_at.isoformat(),
                            "cloud_console_url": agent_response.cloud_console_url,
                            "ssh_url": agent_response.ssh_url,
                            "ssh_command": agent_response.ssh_command,
                        }
                    },
                )

            except Exception as e:
                await db.rollback()
                session.finish_streaming(error=str(e))

    task = asyncio.create_task(run_stop())

    return StreamingResponse(
        _stream_events(session, task),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
