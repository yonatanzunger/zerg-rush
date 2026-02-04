"""Channel credential model for storing channel-specific authentication."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, StringUUID, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import ActiveAgent


class ChannelCredential(Base, UUIDMixin, TimestampMixin):
    """Channel-specific credentials for an agent.

    Stores credentials for messaging channels like WhatsApp, Telegram, etc.
    The actual credential data (e.g., WhatsApp creds.json) is stored in
    the cloud secret manager; this model stores the reference.
    """

    __tablename__ = "channel_credentials"

    agent_id: Mapped[str] = mapped_column(
        StringUUID(),
        ForeignKey("active_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(255))
    credentials_secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    is_paired: Mapped[bool] = mapped_column(Boolean, default=False)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    agent: Mapped["ActiveAgent"] = relationship(
        "ActiveAgent", back_populates="channel_credentials"
    )

    def __repr__(self) -> str:
        paired = "paired" if self.is_paired else "unpaired"
        return f"<ChannelCredential {self.channel_type} ({paired})>"

    def mark_paired(self) -> None:
        """Mark this channel as successfully paired."""
        from datetime import timezone

        self.is_paired = True
        self.last_connected_at = datetime.now(timezone.utc)

    def mark_disconnected(self) -> None:
        """Mark this channel as disconnected."""
        self.is_paired = False
