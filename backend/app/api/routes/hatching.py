"""Hatching (agent setup) routes."""

import asyncio
import base64
import json
from datetime import datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    UserCloudProviders,
    get_client_ip,
    log_action,
)
from app.models import (
    ActiveAgent,
    AgentManifestStep,
    ManifestStepStatus,
    ManifestStepType,
    ChannelCredential,
    HatchingStatus,
)
from app.services import AgentManifestService

router = APIRouter()


# Response models
class ManifestStepResponse(BaseModel):
    """Response for a manifest step."""

    id: str
    step_type: str
    status: str
    order: int
    config: dict | None
    result: dict | None
    error_message: str | None
    completed_at: datetime | None
    is_interactive: bool

    class Config:
        from_attributes = True


class HatchingStatusResponse(BaseModel):
    """Response for hatching status."""

    agent_id: str
    agent_name: str
    hatching_status: str
    steps: list[ManifestStepResponse]
    completed_count: int
    total_count: int
    pending_interactive_steps: list[ManifestStepResponse]


class CompleteStepRequest(BaseModel):
    """Request to complete a manifest step."""

    result: dict | None = None


class WhatsAppPairingResponse(BaseModel):
    """Response when starting WhatsApp pairing."""

    session_id: str
    status: str
    message: str


class WhatsAppQRResponse(BaseModel):
    """Response with WhatsApp QR code."""

    qr_code: str  # Base64-encoded PNG
    expires_at: datetime | None


# Helper functions
async def _get_agent_for_user(
    db: DbSession, agent_id: str, user_id: str
) -> ActiveAgent:
    """Get an agent belonging to the user, or raise 404."""
    result = await db.execute(
        select(ActiveAgent).where(
            ActiveAgent.id == agent_id,
            ActiveAgent.user_id == user_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return agent


def _step_to_response(step: AgentManifestStep) -> ManifestStepResponse:
    """Convert a manifest step to a response model."""
    return ManifestStepResponse(
        id=step.id,
        step_type=step.step_type,
        status=step.status,
        order=step.order,
        config=step.config,
        result=step.result,
        error_message=step.error_message,
        completed_at=step.completed_at,
        is_interactive=step.is_interactive(),
    )


# Routes
@router.get("/{agent_id}/hatching", response_model=HatchingStatusResponse)
async def get_hatching_status(
    agent_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> HatchingStatusResponse:
    """Get the current hatching (setup) status for an agent."""
    agent = await _get_agent_for_user(db, agent_id, current_user.id)

    manifest_service = AgentManifestService(db)
    all_steps = await manifest_service.get_all_steps(agent_id)
    interactive_pending = await manifest_service.get_interactive_pending_steps(agent_id)

    completed_count = sum(
        1 for s in all_steps
        if s.status in (ManifestStepStatus.COMPLETED.value, ManifestStepStatus.SKIPPED.value)
    )

    return HatchingStatusResponse(
        agent_id=agent.id,
        agent_name=agent.name,
        hatching_status=agent.hatching_status,
        steps=[_step_to_response(s) for s in all_steps],
        completed_count=completed_count,
        total_count=len(all_steps),
        pending_interactive_steps=[_step_to_response(s) for s in interactive_pending],
    )


@router.post(
    "/{agent_id}/hatching/steps/{step_id}/complete",
    response_model=ManifestStepResponse,
)
async def complete_hatching_step(
    request: Request,
    agent_id: str,
    step_id: str,
    current_user: CurrentUser,
    db: DbSession,
    body: CompleteStepRequest,
) -> ManifestStepResponse:
    """Mark a hatching step as completed."""
    agent = await _get_agent_for_user(db, agent_id, current_user.id)

    # Verify the step belongs to this agent
    manifest_service = AgentManifestService(db)
    step = await manifest_service.get_step_by_id(step_id)

    if not step or step.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manifest step not found",
        )

    # Complete the step
    step = await manifest_service.complete_step(step_id, body.result)

    # Update agent hatching status
    await manifest_service.update_agent_hatching_status(agent_id)

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="hatching.step.complete",
        target_type="manifest_step",
        target_id=step_id,
        details={
            "agent_id": agent_id,
            "step_type": step.step_type,
        },
        ip_address=get_client_ip(request),
    )

    await db.commit()
    return _step_to_response(step)


@router.post(
    "/{agent_id}/hatching/steps/{step_id}/fail",
    response_model=ManifestStepResponse,
)
async def fail_hatching_step(
    request: Request,
    agent_id: str,
    step_id: str,
    current_user: CurrentUser,
    db: DbSession,
    error_message: str = "Step failed",
) -> ManifestStepResponse:
    """Mark a hatching step as failed."""
    agent = await _get_agent_for_user(db, agent_id, current_user.id)

    manifest_service = AgentManifestService(db)
    step = await manifest_service.get_step_by_id(step_id)

    if not step or step.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manifest step not found",
        )

    step = await manifest_service.fail_step(step_id, error_message)
    await manifest_service.update_agent_hatching_status(agent_id)

    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="hatching.step.fail",
        target_type="manifest_step",
        target_id=step_id,
        details={
            "agent_id": agent_id,
            "step_type": step.step_type,
            "error": error_message,
        },
        ip_address=get_client_ip(request),
    )

    await db.commit()
    return _step_to_response(step)


# WhatsApp Pairing Routes
@router.post(
    "/{agent_id}/hatching/whatsapp/start-pairing",
    response_model=WhatsAppPairingResponse,
)
async def start_whatsapp_pairing(
    request: Request,
    agent_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> WhatsAppPairingResponse:
    """Start WhatsApp pairing process on the running agent."""
    agent = await _get_agent_for_user(db, agent_id, current_user.id)

    # Verify agent is running
    if agent.vm_status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent VM must be running to pair WhatsApp. Current status: {agent.vm_status}",
        )

    # Verify WhatsApp step exists and is pending
    manifest_service = AgentManifestService(db)
    whatsapp_step = await manifest_service.get_step_by_type(
        agent_id, ManifestStepType.CHANNEL_WHATSAPP.value
    )

    if not whatsapp_step:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WhatsApp is not enabled for this agent",
        )

    if whatsapp_step.status == ManifestStepStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WhatsApp is already paired",
        )

    # Mark step as in progress
    await manifest_service.start_step(whatsapp_step.id)
    await manifest_service.update_agent_hatching_status(agent_id)

    # Proxy request to OpenClaw on the VM
    agent_url = _get_agent_url(agent)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{agent_url}/api/channels/whatsapp/pair",
                json={"accountId": "default"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to start pairing on agent: {str(e)}",
        )

    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="hatching.whatsapp.start_pairing",
        target_type="agent",
        target_id=agent_id,
        ip_address=get_client_ip(request),
    )

    await db.commit()

    return WhatsAppPairingResponse(
        session_id=data.get("sessionId", "default"),
        status="pairing",
        message="Scan the QR code with WhatsApp to complete pairing",
    )


@router.get(
    "/{agent_id}/hatching/whatsapp/qr",
    response_model=WhatsAppQRResponse,
)
async def get_whatsapp_qr(
    agent_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> WhatsAppQRResponse:
    """Get the current WhatsApp QR code for pairing."""
    agent = await _get_agent_for_user(db, agent_id, current_user.id)

    if agent.vm_status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent VM is not running",
        )

    # Proxy request to OpenClaw
    agent_url = _get_agent_url(agent)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{agent_url}/api/channels/whatsapp/qr",
                params={"accountId": "default"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to get QR code from agent: {str(e)}",
        )

    return WhatsAppQRResponse(
        qr_code=data.get("qrCode", ""),
        expires_at=data.get("expiresAt"),
    )


@router.post("/{agent_id}/hatching/whatsapp/cancel")
async def cancel_whatsapp_pairing(
    request: Request,
    agent_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> dict:
    """Cancel an in-progress WhatsApp pairing attempt."""
    agent = await _get_agent_for_user(db, agent_id, current_user.id)

    manifest_service = AgentManifestService(db)
    whatsapp_step = await manifest_service.get_step_by_type(
        agent_id, ManifestStepType.CHANNEL_WHATSAPP.value
    )

    if whatsapp_step and whatsapp_step.status == ManifestStepStatus.IN_PROGRESS.value:
        # Reset to pending
        whatsapp_step.status = ManifestStepStatus.PENDING.value
        await manifest_service.update_agent_hatching_status(agent_id)

    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="hatching.whatsapp.cancel",
        target_type="agent",
        target_id=agent_id,
        ip_address=get_client_ip(request),
    )

    await db.commit()
    return {"status": "cancelled"}


@router.websocket("/{agent_id}/hatching/whatsapp/ws")
async def whatsapp_pairing_websocket(
    websocket: WebSocket,
    agent_id: str,
    db: DbSession,
) -> None:
    """WebSocket for real-time WhatsApp pairing status updates.

    Messages sent:
    - {"type": "qr", "qrCode": "...", "expiresAt": "..."}
    - {"type": "paired", "accountId": "..."}
    - {"type": "error", "message": "..."}
    - {"type": "ping"}
    """
    await websocket.accept()

    # Note: WebSocket auth would need to be handled separately
    # For now, we'll rely on the agent_id being valid

    try:
        # Get agent
        result = await db.execute(
            select(ActiveAgent).where(ActiveAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            await websocket.send_json({"type": "error", "message": "Agent not found"})
            await websocket.close()
            return

        if agent.vm_status != "running":
            await websocket.send_json({"type": "error", "message": "Agent not running"})
            await websocket.close()
            return

        # Poll the agent for pairing status
        agent_url = _get_agent_url(agent)
        last_qr = None

        while True:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Check pairing status
                    response = await client.get(
                        f"{agent_url}/api/channels/whatsapp/status",
                        params={"accountId": "default"},
                    )
                    response.raise_for_status()
                    status_data = response.json()

                    if status_data.get("paired"):
                        # Pairing complete
                        await websocket.send_json({
                            "type": "paired",
                            "accountId": status_data.get("accountId", "default"),
                        })

                        # Update manifest step
                        manifest_service = AgentManifestService(db)
                        step = await manifest_service.get_step_by_type(
                            agent_id, ManifestStepType.CHANNEL_WHATSAPP.value
                        )
                        if step:
                            await manifest_service.complete_step(
                                step.id,
                                {"account_id": status_data.get("accountId", "default")},
                            )
                            await manifest_service.update_agent_hatching_status(agent_id)
                            await db.commit()

                        await websocket.close()
                        return

                    # Get QR code if pairing in progress
                    qr_response = await client.get(
                        f"{agent_url}/api/channels/whatsapp/qr",
                        params={"accountId": "default"},
                    )
                    if qr_response.status_code == 200:
                        qr_data = qr_response.json()
                        current_qr = qr_data.get("qrCode")
                        if current_qr and current_qr != last_qr:
                            last_qr = current_qr
                            await websocket.send_json({
                                "type": "qr",
                                "qrCode": current_qr,
                                "expiresAt": qr_data.get("expiresAt"),
                            })

            except httpx.HTTPError:
                # Agent might be restarting, keep trying
                pass

            # Send ping to keep connection alive
            await websocket.send_json({"type": "ping"})

            # Wait before next poll
            await asyncio.sleep(2)

    except WebSocketDisconnect:
        pass


def _get_agent_url(agent: ActiveAgent) -> str:
    """Get the base URL for an agent's API."""
    # Use internal IP if available, otherwise external
    ip = agent.vm_internal_ip or agent.vm_external_ip
    if not ip:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent has no IP address",
        )
    return f"http://{ip}:{agent.gateway_port}"
