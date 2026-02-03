"""Credential model."""

from typing import TYPE_CHECKING, Literal

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User

CredentialType = Literal["llm", "cloud", "utility"]


class Credential(Base, UUIDMixin, TimestampMixin):
    """User credential stored in keyvault."""

    __tablename__ = "credentials"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # llm, cloud, utility
    description: Mapped[str | None] = mapped_column(Text)
    secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="credentials")

    def __repr__(self) -> str:
        return f"<Credential {self.name} ({self.type})>"
