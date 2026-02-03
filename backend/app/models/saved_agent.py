"""Saved Agent (template/snapshot) model."""

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.agent import ActiveAgent
    from app.models.setup_script import SetupScript


class SavedAgent(Base, UUIDMixin, TimestampMixin):
    """Saved agent template or snapshot."""

    __tablename__ = "saved_agents"

    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_type: Mapped[str] = mapped_column(String(50), nullable=False)
    setup_script_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("setup_scripts.id")
    )
    config_snapshot: Mapped[dict | None] = mapped_column(JSON)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    source_agent_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False))
    description: Mapped[str | None] = mapped_column(Text)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="saved_agents")
    setup_script: Mapped["SetupScript | None"] = relationship("SetupScript")
    deployed_agents: Mapped[list["ActiveAgent"]] = relationship(
        "ActiveAgent", back_populates="template"
    )

    def __repr__(self) -> str:
        starred = "*" if self.is_starred else ""
        return f"<SavedAgent {self.name}{starred}>"
