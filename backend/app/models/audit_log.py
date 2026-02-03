"""Audit Log model."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid, event, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AuditLog(Base):
    """Append-only audit log of all user actions."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False))
    details: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship (no cascade delete - logs must be preserved)
    user = relationship("User", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog {self.action_type} by {self.user_id}>"


# Prevent updates and deletes on audit logs at the ORM level
@event.listens_for(AuditLog, "before_update")
def prevent_audit_log_update(mapper, connection, target):
    """Prevent updates to audit logs."""
    raise ValueError("Audit logs cannot be updated")


@event.listens_for(AuditLog, "before_delete")
def prevent_audit_log_delete(mapper, connection, target):
    """Prevent deletion of audit logs."""
    raise ValueError("Audit logs cannot be deleted")
