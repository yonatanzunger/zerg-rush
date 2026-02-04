"""Active Agent model."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.saved_agent import SavedAgent
    from app.models.credential import Credential
    from app.models.agent_manifest import AgentManifestStep
    from app.models.agent_config import AgentConfig
    from app.models.channel_credential import ChannelCredential


class HatchingStatus(str, Enum):
    """Status of agent hatching (setup) process."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


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

    # Hatching (setup) status
    hatching_status: Mapped[str] = mapped_column(
        String(20), default=HatchingStatus.PENDING.value
    )
    config_version: Mapped[int] = mapped_column(Integer, default=1)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="agents")
    template: Mapped["SavedAgent | None"] = relationship(
        "SavedAgent", back_populates="deployed_agents"
    )
    agent_credentials: Mapped[list["AgentCredential"]] = relationship(
        "AgentCredential", back_populates="agent", cascade="all, delete-orphan"
    )
    manifest_steps: Mapped[list["AgentManifestStep"]] = relationship(
        "AgentManifestStep", back_populates="agent", cascade="all, delete-orphan"
    )
    config: Mapped["AgentConfig | None"] = relationship(
        "AgentConfig", back_populates="agent", uselist=False, cascade="all, delete-orphan"
    )
    channel_credentials: Mapped[list["ChannelCredential"]] = relationship(
        "ChannelCredential", back_populates="agent", cascade="all, delete-orphan"
    )

    @property
    def credentials(self) -> list["Credential"]:
        """Get all credentials granted to this agent."""
        return [ac.credential for ac in self.agent_credentials]

    def __repr__(self) -> str:
        return f"<ActiveAgent {self.name} ({self.vm_status})>"

    def is_hatching_complete(self) -> bool:
        """Check if hatching is complete."""
        return self.hatching_status == HatchingStatus.COMPLETED.value

    def get_pending_manifest_steps(self) -> list["AgentManifestStep"]:
        """Get all pending manifest steps."""
        from app.models.agent_manifest import ManifestStepStatus

        return [
            step
            for step in self.manifest_steps
            if step.status == ManifestStepStatus.PENDING.value
        ]

    def get_interactive_pending_steps(self) -> list["AgentManifestStep"]:
        """Get pending steps that require user interaction."""
        return [step for step in self.get_pending_manifest_steps() if step.is_interactive()]


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
