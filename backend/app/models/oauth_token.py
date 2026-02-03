"""OAuth token model for storing user cloud credentials."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class UserOAuthToken(Base, UUIDMixin, TimestampMixin):
    """Stores encrypted OAuth tokens for cloud provider operations.

    Each user can have one token per cloud provider (GCP, Azure).
    Tokens are encrypted at rest using Fernet encryption.
    """

    __tablename__ = "user_oauth_tokens"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_oauth_token"),
    )

    # Foreign key to user
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Cloud provider: "gcp" or "azure"
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # Encrypted token storage
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # Token metadata
    token_type: Mapped[str] = mapped_column(String(50), default="Bearer")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scopes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of scopes

    # Cloud-specific metadata (user's cloud project/subscription)
    project_id: Mapped[str | None] = mapped_column(String(255))  # GCP project ID
    subscription_id: Mapped[str | None] = mapped_column(String(255))  # Azure subscription
    tenant_id: Mapped[str | None] = mapped_column(String(255))  # Azure tenant ID

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="oauth_tokens")

    def __repr__(self) -> str:
        return f"<UserOAuthToken {self.provider} for user {self.user_id}>"
