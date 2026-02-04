"""Agent configuration model for storing OpenClaw config."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import ActiveAgent


class AgentConfig(Base, UUIDMixin, TimestampMixin):
    """Generated OpenClaw configuration for an agent.

    Stores the configuration template with placeholders for secrets,
    along with references to the actual secret values stored in the
    cloud secret manager.
    """

    __tablename__ = "agent_configs"

    agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("active_agents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    config_template: Mapped[dict] = mapped_column(JSON, nullable=False)
    gateway_port: Mapped[int] = mapped_column(Integer, default=18789)
    gateway_auth_token_ref: Mapped[str | None] = mapped_column(String(255))
    workspace_path: Mapped[str] = mapped_column(
        String(255), default="~/.openclaw/workspace"
    )
    enabled_channels: Mapped[list] = mapped_column(JSON, default=list)
    env_var_refs: Mapped[dict] = mapped_column(JSON, default=dict)
    model_primary: Mapped[str | None] = mapped_column(String(100))
    whatsapp_allow_from: Mapped[list | None] = mapped_column(JSON)

    # Relationships
    agent: Mapped["ActiveAgent"] = relationship(
        "ActiveAgent", back_populates="config"
    )

    def __repr__(self) -> str:
        channels = ", ".join(self.enabled_channels) if self.enabled_channels else "none"
        return f"<AgentConfig port={self.gateway_port} channels=[{channels}]>"

    def has_channel(self, channel: str) -> bool:
        """Check if a channel is enabled."""
        return channel in (self.enabled_channels or [])
