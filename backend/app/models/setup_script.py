"""Setup Script model."""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class SetupScript(Base, UUIDMixin, TimestampMixin):
    """Setup script for agent platforms."""

    __tablename__ = "setup_scripts"

    platform_type: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_version: Mapped[str | None] = mapped_column(String(50))
    script_content: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        version = f"@{self.platform_version}" if self.platform_version else ""
        system = " (system)" if self.is_system else ""
        return f"<SetupScript {self.platform_type}{version}{system}>"
