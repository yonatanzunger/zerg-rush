"""Base model class for SQLAlchemy."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class StringUUID(TypeDecorator):
    """UUID type that stores as PostgreSQL UUID but returns strings in Python.

    This resolves the mismatch between asyncpg (returns uuid.UUID objects)
    and code that expects string UUIDs.
    """

    impl = PG_UUID(as_uuid=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Convert string to UUID for database storage."""
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        return UUID(value)

    def process_result_value(self, value, dialect):
        """Convert UUID to string when reading from database."""
        if value is None:
            return None
        return str(value)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDMixin:
    """Mixin for UUID primary key."""

    id: Mapped[str] = mapped_column(
        StringUUID(),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
