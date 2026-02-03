"""Saved agents (templates) routes."""

from datetime import datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession, log_action, get_client_ip
from app.models import SavedAgent

router = APIRouter()


class SavedAgentResponse(BaseModel):
    """Saved agent response."""

    id: str
    name: str
    platform_type: str
    is_starred: bool
    description: str | None
    config_snapshot: dict | None
    source_agent_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class SavedAgentListResponse(BaseModel):
    """List of saved agents response."""

    saved_agents: list[SavedAgentResponse]
    total: int


class UpdateSavedAgentRequest(BaseModel):
    """Request to update a saved agent."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


@router.get("", response_model=SavedAgentListResponse)
async def list_saved_agents(
    current_user: CurrentUser,
    db: DbSession,
    starred_only: Annotated[bool, Query()] = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SavedAgentListResponse:
    """List all saved agents for the current user."""
    query = select(SavedAgent).where(SavedAgent.user_id == current_user.id)

    if starred_only:
        query = query.where(SavedAgent.is_starred == True)

    # Get total count
    count_result = await db.execute(query)
    total = len(count_result.scalars().all())

    # Get paginated results
    result = await db.execute(
        query.order_by(SavedAgent.created_at.desc()).offset(skip).limit(limit)
    )
    saved_agents = result.scalars().all()

    return SavedAgentListResponse(
        saved_agents=[SavedAgentResponse.model_validate(sa) for sa in saved_agents],
        total=total,
    )


@router.get("/starred", response_model=SavedAgentListResponse)
async def list_starred_agents(
    current_user: CurrentUser,
    db: DbSession,
) -> SavedAgentListResponse:
    """List all starred saved agents (templates) for the current user."""
    result = await db.execute(
        select(SavedAgent)
        .where(
            SavedAgent.user_id == current_user.id,
            SavedAgent.is_starred == True,
        )
        .order_by(SavedAgent.name)
    )
    saved_agents = result.scalars().all()

    return SavedAgentListResponse(
        saved_agents=[SavedAgentResponse.model_validate(sa) for sa in saved_agents],
        total=len(saved_agents),
    )


@router.get("/{saved_agent_id}", response_model=SavedAgentResponse)
async def get_saved_agent(
    current_user: CurrentUser,
    db: DbSession,
    saved_agent_id: str,
) -> SavedAgent:
    """Get a specific saved agent by ID."""
    result = await db.execute(
        select(SavedAgent).where(
            SavedAgent.id == saved_agent_id,
            SavedAgent.user_id == current_user.id,
        )
    )
    saved_agent = result.scalar_one_or_none()

    if not saved_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved agent not found",
        )

    return saved_agent


@router.put("/{saved_agent_id}", response_model=SavedAgentResponse)
async def update_saved_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    saved_agent_id: str,
    body: UpdateSavedAgentRequest,
) -> SavedAgent:
    """Update a saved agent's metadata."""
    result = await db.execute(
        select(SavedAgent).where(
            SavedAgent.id == saved_agent_id,
            SavedAgent.user_id == current_user.id,
        )
    )
    saved_agent = result.scalar_one_or_none()

    if not saved_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved agent not found",
        )

    # Update fields
    if body.name is not None:
        saved_agent.name = body.name
    if body.description is not None:
        saved_agent.description = body.description

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="saved_agent.update",
        target_type="saved_agent",
        target_id=saved_agent_id,
        details=body.model_dump(exclude_none=True),
        ip_address=get_client_ip(request),
    )

    await db.commit()
    await db.refresh(saved_agent)

    return saved_agent


@router.delete("/{saved_agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    saved_agent_id: str,
) -> None:
    """Delete a saved agent."""
    result = await db.execute(
        select(SavedAgent).where(
            SavedAgent.id == saved_agent_id,
            SavedAgent.user_id == current_user.id,
        )
    )
    saved_agent = result.scalar_one_or_none()

    if not saved_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved agent not found",
        )

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="saved_agent.delete",
        target_type="saved_agent",
        target_id=saved_agent_id,
        details={"name": saved_agent.name},
        ip_address=get_client_ip(request),
    )

    await db.delete(saved_agent)
    await db.commit()


@router.post("/{saved_agent_id}/star", response_model=SavedAgentResponse)
async def star_saved_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    saved_agent_id: str,
) -> SavedAgent:
    """Star a saved agent (mark as template)."""
    result = await db.execute(
        select(SavedAgent).where(
            SavedAgent.id == saved_agent_id,
            SavedAgent.user_id == current_user.id,
        )
    )
    saved_agent = result.scalar_one_or_none()

    if not saved_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved agent not found",
        )

    saved_agent.is_starred = True

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="saved_agent.star",
        target_type="saved_agent",
        target_id=saved_agent_id,
        ip_address=get_client_ip(request),
    )

    await db.commit()
    await db.refresh(saved_agent)

    return saved_agent


@router.delete("/{saved_agent_id}/star", response_model=SavedAgentResponse)
async def unstar_saved_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    saved_agent_id: str,
) -> SavedAgent:
    """Unstar a saved agent."""
    result = await db.execute(
        select(SavedAgent).where(
            SavedAgent.id == saved_agent_id,
            SavedAgent.user_id == current_user.id,
        )
    )
    saved_agent = result.scalar_one_or_none()

    if not saved_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved agent not found",
        )

    saved_agent.is_starred = False

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="saved_agent.unstar",
        target_type="saved_agent",
        target_id=saved_agent_id,
        ip_address=get_client_ip(request),
    )

    await db.commit()
    await db.refresh(saved_agent)

    return saved_agent


@router.post("/{saved_agent_id}/copy", response_model=SavedAgentResponse)
async def copy_saved_agent(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    saved_agent_id: str,
    name: Annotated[str | None, Query()] = None,
) -> SavedAgent:
    """Create a copy of a saved agent."""
    result = await db.execute(
        select(SavedAgent).where(
            SavedAgent.id == saved_agent_id,
            SavedAgent.user_id == current_user.id,
        )
    )
    saved_agent = result.scalar_one_or_none()

    if not saved_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved agent not found",
        )

    # Create copy
    copy_name = name or f"{saved_agent.name} (copy)"
    new_saved_agent = SavedAgent(
        id=str(uuid4()),
        user_id=current_user.id,
        name=copy_name,
        platform_type=saved_agent.platform_type,
        setup_script_id=saved_agent.setup_script_id,
        config_snapshot=saved_agent.config_snapshot,
        is_starred=False,
        description=saved_agent.description,
    )
    db.add(new_saved_agent)

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="saved_agent.copy",
        target_type="saved_agent",
        target_id=saved_agent_id,
        details={"new_id": new_saved_agent.id, "name": copy_name},
        ip_address=get_client_ip(request),
    )

    await db.commit()
    await db.refresh(new_saved_agent)

    return new_saved_agent
