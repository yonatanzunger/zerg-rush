"""Active Agent model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.saved_agent import SavedAgent
    from app.models.credential import Credential


class ActiveAgent(Base, UUIDMixin, TimestampMixin):
    """Active agent running in a VM."""

    __tablename__ = "active_agents"

    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vm_id: Mapped[str] = mapped_column(String(255), nullable=False)
    vm_size: Mapped[str] = mapped_column(String(50), nullable=False)
    vm_status: Mapped[str] = mapped_column(String(50), nullable=False, default="creating")
    vm_internal_ip: Mapped[str | None] = mapped_column(String(45))
    vm_external_ip: Mapped[str | None] = mapped_column(String(45))
    vm_zone: Mapped[str | None] = mapped_column(String(100))
    cloud_provider: Mapped[str] = mapped_column(String(20), default="gcp")
    bucket_id: Mapped[str] = mapped_column(String(255), nullable=False)
    current_task: Mapped[str | None] = mapped_column(Text)
    platform_type: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_version: Mapped[str | None] = mapped_column(String(50))
    template_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("saved_agents.id")
    )
    gateway_port: Mapped[int] = mapped_column(Integer, default=18789)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="agents")
    template: Mapped["SavedAgent | None"] = relationship(
        "SavedAgent", back_populates="deployed_agents"
    )
    agent_credentials: Mapped[list["AgentCredential"]] = relationship(
        "AgentCredential", back_populates="agent", cascade="all, delete-orphan"
    )

    @property
    def credentials(self) -> list["Credential"]:
        """Get all credentials granted to this agent."""
        return [ac.credential for ac in self.agent_credentials]

    def __repr__(self) -> str:
        return f"<ActiveAgent {self.name} ({self.vm_status})>"


class AgentCredential(Base):
    """Junction table for agent credentials."""

    __tablename__ = "agent_credentials"

    agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("active_agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    credential_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("credentials.id"),
        primary_key=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    agent: Mapped["ActiveAgent"] = relationship(
        "ActiveAgent", back_populates="agent_credentials"
    )
    credential: Mapped["Credential"] = relationship("Credential")

    def __repr__(self) -> str:
        return f"<AgentCredential agent={self.agent_id} cred={self.credential_id}>"
