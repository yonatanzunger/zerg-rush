"""User model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import ActiveAgent
    from app.models.saved_agent import SavedAgent
    from app.models.credential import Credential
    from app.models.audit_log import AuditLog
    from app.models.oauth_token import UserOAuthToken


class User(Base, UUIDMixin, TimestampMixin):
    """User account model."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oauth_provider", "oauth_subject", name="uq_user_oauth"),
    )

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    oauth_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    oauth_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    agents: Mapped[list["ActiveAgent"]] = relationship(
        "ActiveAgent", back_populates="user", cascade="all, delete-orphan"
    )
    saved_agents: Mapped[list["SavedAgent"]] = relationship(
        "SavedAgent", back_populates="user", cascade="all, delete-orphan"
    )
    credentials: Mapped[list["Credential"]] = relationship(
        "Credential", back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="user"
    )
    oauth_tokens: Mapped[list["UserOAuthToken"]] = relationship(
        "UserOAuthToken", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"
