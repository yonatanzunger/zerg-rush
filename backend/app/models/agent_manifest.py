"""Agent manifest step model for tracking setup progress."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, StringUUID, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import ActiveAgent


class ManifestStepStatus(str, Enum):
    """Status of a manifest step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ManifestStepType(str, Enum):
    """Type of manifest step."""

    # Credential steps
    CREDENTIAL_LLM = "credential_llm"
    CREDENTIAL_UTILITY = "credential_utility"

    # Channel steps (interactive)
    CHANNEL_WHATSAPP = "channel_whatsapp"
    CHANNEL_TELEGRAM = "channel_telegram"
    CHANNEL_DISCORD = "channel_discord"

    # Configuration steps
    CONFIG_GATEWAY = "config_gateway"
    CONFIG_WORKSPACE = "config_workspace"


class AgentManifestStep(Base, UUIDMixin, TimestampMixin):
    """Individual step in an agent's setup manifest.

    Tracks required setup steps for an agent, including:
    - Credential requirements (LLM API keys, etc.)
    - Channel pairing (WhatsApp QR code, etc.)
    - Configuration steps (gateway setup, etc.)
    """

    __tablename__ = "agent_manifest_steps"

    agent_id: Mapped[str] = mapped_column(
        StringUUID(),
        ForeignKey("active_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ManifestStepStatus.PENDING.value
    )
    order: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    agent: Mapped["ActiveAgent"] = relationship(
        "ActiveAgent", back_populates="manifest_steps"
    )

    def __repr__(self) -> str:
        return f"<AgentManifestStep {self.step_type} ({self.status})>"

    def is_interactive(self) -> bool:
        """Check if this step requires user interaction."""
        return self.step_type in (
            ManifestStepType.CHANNEL_WHATSAPP.value,
            ManifestStepType.CHANNEL_TELEGRAM.value,
            ManifestStepType.CHANNEL_DISCORD.value,
        )

    def mark_completed(self, result: dict | None = None) -> None:
        """Mark this step as completed."""
        from datetime import datetime, timezone

        self.status = ManifestStepStatus.COMPLETED.value
        self.completed_at = datetime.now(timezone.utc)
        if result:
            self.result = result

    def mark_failed(self, error_message: str) -> None:
        """Mark this step as failed."""
        self.status = ManifestStepStatus.FAILED.value
        self.error_message = error_message

    def mark_in_progress(self) -> None:
        """Mark this step as in progress."""
        self.status = ManifestStepStatus.IN_PROGRESS.value
