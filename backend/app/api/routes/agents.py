"""Agent management routes."""

from datetime import datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser, DbSession, log_action, get_client_ip, UserCloudProviders
from app.cloud.factory import get_providers, CloudProviders
from app.cloud.interfaces import VMConfig, VMStatus
from app.config import get_settings
from app.models import ActiveAgent, SavedAgent, Credential, AgentCredential

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
    bucket_id: str
    current_task: str | None
    platform_type: str
    platform_version: str | None
    template_id: str | None
    gateway_port: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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


# Helper functions
def get_startup_script(platform_type: str, platform_version: str | None = None) -> str:
    """Get the startup script for an agent platform."""
    if platform_type == "openclaw":
        return """#!/bin/bash
set -e

# Update system
apt-get update
apt-get install -y curl

# Install Node.js 22
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

# Install pnpm
npm install -g pnpm

# Install openclaw
pnpm add -g openclaw@latest

# Create openclaw user
useradd -m -s /bin/bash openclaw || true

# Create config directory
sudo -u openclaw mkdir -p /home/openclaw/.openclaw

# Signal that setup is complete
touch /home/openclaw/.openclaw/setup-complete
"""
    else:
        raise ValueError(f"Unknown platform type: {platform_type}")


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
        agents=[AgentResponse.model_validate(a) for a in agents],
        total=total,
    )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    providers: UserCloudProviders,
    body: CreateAgentRequest,
) -> ActiveAgent:
    """Create a new agent."""

    # Use default VM size if not specified
    vm_size = body.vm_size or settings.default_vm_size

    # Generate unique identifiers
    agent_id = str(uuid4())
    vm_name = f"zr-agent-{agent_id[:8]}"
    bucket_name = f"agent-{agent_id[:8]}"

    # Validate template if specified
    template = None
    if body.template_id:
        result = await db.execute(
            select(SavedAgent).where(
                SavedAgent.id == body.template_id,
                SavedAgent.user_id == current_user.id,
            )
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template not found",
            )

    # Validate credentials
    if body.credential_ids:
        result = await db.execute(
            select(Credential).where(
                Credential.id.in_(body.credential_ids),
                Credential.user_id == current_user.id,
            )
        )
        credentials = result.scalars().all()
        if len(credentials) != len(body.credential_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more credentials not found",
            )

    # Create storage bucket for data exchange
    try:
        bucket_id = await providers.storage.create_bucket(
            name=bucket_name,
            user_id=current_user.id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create storage bucket: {str(e)}",
        )

    # Create VM
    try:
        vm_config = VMConfig(
            name=vm_name,
            size=vm_size,
            image="default",
            user_id=current_user.id,
            agent_id=agent_id,
            startup_script=get_startup_script(body.platform_type),
        )
        vm_instance = await providers.vm.create_vm(vm_config)
    except Exception as e:
        # Clean up bucket on failure
        try:
            await providers.storage.delete_bucket(bucket_id)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create VM: {str(e)}",
        )

    # Create agent record
    agent = ActiveAgent(
        id=agent_id,
        user_id=current_user.id,
        name=body.name,
        vm_id=vm_instance.vm_id,
        vm_size=vm_size,
        vm_status=vm_instance.status.value,
        vm_internal_ip=vm_instance.internal_ip,
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
        user_id=current_user.id,
        action_type="agent.create",
        target_type="agent",
        target_id=agent_id,
        details={
            "name": body.name,
            "platform_type": body.platform_type,
            "vm_size": vm_size,
            "template_id": body.template_id,
        },
        ip_address=get_client_ip(request),
    )

    await db.commit()
    await db.refresh(agent)

    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    current_user: CurrentUser,
    db: DbSession,
    agent_id: str,
) -> ActiveAgent:
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

    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    providers: UserCloudProviders,
    agent_id: str,
) -> None:
    """Delete an agent (destroys VM and bucket)."""

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

    # Delete VM
    try:
        await providers.vm.delete_vm(agent.vm_id)
    except Exception as e:
        # Log but continue - VM might already be deleted
        pass

    # Delete storage bucket
    try:
        await providers.storage.delete_bucket(agent.bucket_id)
    except Exception as e:
        # Log but continue - bucket might already be deleted
        pass

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="agent.delete",
        target_type="agent",
        target_id=agent_id,
        details={"name": agent.name},
        ip_address=get_client_ip(request),
    )

    # Delete from database
    await db.delete(agent)
    await db.commit()


@router.post("/{agent_id}/start", response_model=AgentResponse)
async def start_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    providers: UserCloudProviders,
    agent_id: str,
) -> ActiveAgent:
    """Start a stopped agent."""

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

    if agent.vm_status not in [VMStatus.STOPPED.value, VMStatus.ERROR.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent cannot be started from status: {agent.vm_status}",
        )

    # Start VM
    try:
        await providers.vm.start_vm(agent.vm_id)
        vm_instance = await providers.vm.get_vm_status(agent.vm_id)
        agent.vm_status = vm_instance.status.value
        agent.vm_internal_ip = vm_instance.internal_ip
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start VM: {str(e)}",
        )

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="agent.start",
        target_type="agent",
        target_id=agent_id,
        ip_address=get_client_ip(request),
    )

    await db.commit()
    await db.refresh(agent)

    return agent


@router.post("/{agent_id}/stop", response_model=AgentResponse)
async def stop_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    providers: UserCloudProviders,
    agent_id: str,
) -> ActiveAgent:
    """Stop a running agent."""

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
            detail=f"Agent cannot be stopped from status: {agent.vm_status}",
        )

    # Stop VM
    try:
        await providers.vm.stop_vm(agent.vm_id)
        vm_instance = await providers.vm.get_vm_status(agent.vm_id)
        agent.vm_status = vm_instance.status.value
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop VM: {str(e)}",
        )

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="agent.stop",
        target_type="agent",
        target_id=agent_id,
        ip_address=get_client_ip(request),
    )

    await db.commit()
    await db.refresh(agent)

    return agent


@router.get("/{agent_id}/status", response_model=AgentResponse)
async def get_agent_status(
    current_user: CurrentUser,
    db: DbSession,
    providers: UserCloudProviders,
    agent_id: str,
) -> ActiveAgent:
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
        await db.commit()
        await db.refresh(agent)
    except Exception as e:
        # If VM is not found, mark as error
        agent.vm_status = VMStatus.ERROR.value
        await db.commit()

    return agent


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
