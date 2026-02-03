"""Audit logs routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession
from app.models import AuditLog

router = APIRouter()


class AuditLogResponse(BaseModel):
    """Audit log entry response."""

    id: str
    action_type: str
    target_type: str | None
    target_id: str | None
    details: dict | None
    ip_address: str | None
    timestamp: datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """List of audit logs response."""

    logs: list[AuditLogResponse]
    total: int
    has_more: bool


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    current_user: CurrentUser,
    db: DbSession,
    action_type: Annotated[str | None, Query()] = None,
    target_type: Annotated[str | None, Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditLogListResponse:
    """List audit logs for the current user."""
    query = select(AuditLog).where(AuditLog.user_id == current_user.id)

    if action_type:
        query = query.where(AuditLog.action_type == action_type)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)

    # Get total count
    count_result = await db.execute(query)
    total = len(count_result.scalars().all())

    # Get paginated results
    result = await db.execute(
        query.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit + 1)
    )
    logs = result.scalars().all()

    # Check if there are more results
    has_more = len(logs) > limit
    if has_more:
        logs = logs[:limit]

    return AuditLogListResponse(
        logs=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        has_more=has_more,
    )


@router.get("/export")
async def export_audit_logs(
    current_user: CurrentUser,
    db: DbSession,
    format: Annotated[str, Query()] = "csv",
) -> StreamingResponse:
    """Export audit logs as CSV or JSON."""
    import csv
    import io
    import json

    # Get all logs for user
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.user_id == current_user.id)
        .order_by(AuditLog.timestamp.desc())
    )
    logs = result.scalars().all()

    if format == "json":
        # Export as JSON
        data = [
            {
                "id": log.id,
                "action_type": log.action_type,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "details": log.details,
                "ip_address": log.ip_address,
                "timestamp": log.timestamp.isoformat(),
            }
            for log in logs
        ]
        content = json.dumps(data, indent=2)
        media_type = "application/json"
        filename = "audit_logs.json"
    else:
        # Export as CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["ID", "Timestamp", "Action", "Target Type", "Target ID", "Details", "IP"]
        )
        for log in logs:
            writer.writerow(
                [
                    log.id,
                    log.timestamp.isoformat(),
                    log.action_type,
                    log.target_type or "",
                    log.target_id or "",
                    json.dumps(log.details) if log.details else "",
                    log.ip_address or "",
                ]
            )
        content = output.getvalue()
        media_type = "text/csv"
        filename = "audit_logs.csv"

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
