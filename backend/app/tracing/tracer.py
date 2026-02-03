"""Event tracing system for debugging request flows."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ContextManager, Generator, Protocol
from uuid import uuid4

from app.config import get_settings

if TYPE_CHECKING:
    from app.models import User


@dataclass
class TraceEvent:
    """A single trace event in the session."""

    timestamp: datetime
    message: str
    depth: int
    kwargs: dict[str, Any]
    duration_ms: float | None = None


class Session(Protocol):
    """Protocol for trace sessions."""

    def log(self, message: str, **kwargs: Any) -> None:
        """Log a message with optional key-value context."""
        ...

    def span(self, name: str) -> ContextManager[None]:
        """Create a nested span for tracking call hierarchy."""
        ...

    def set_user(self, user: "User") -> None:
        """Set user information after authentication."""
        ...

    def finalize(self) -> None:
        """Finalize the session and output trace if debug enabled."""
        ...


@dataclass
class ActiveSession:
    """Active trace session that captures events."""

    session_id: str
    client_ip: str | None
    request_path: str | None
    request_method: str | None
    start_time: datetime
    user_id: str | None = None
    user_email: str | None = None
    user_name: str | None = None
    _events: list[TraceEvent] = field(default_factory=list)
    _current_depth: int = 0
    _span_stack: list[tuple[str, datetime]] = field(default_factory=list)

    def log(self, message: str, **kwargs: Any) -> None:
        """Log an event at the current nesting depth."""
        self._events.append(
            TraceEvent(
                timestamp=datetime.now(timezone.utc),
                message=message,
                depth=self._current_depth,
                kwargs=kwargs,
            )
        )

    @contextmanager
    def span(self, name: str) -> Generator[None, None, None]:  # type: ignore[override]
        """Create a nested span for hierarchical tracing."""
        start_time = datetime.now(timezone.utc)
        self._span_stack.append((name, start_time))
        self.log(f">>> {name}")
        self._current_depth += 1

        try:
            yield
        finally:
            self._current_depth -= 1
            span_name, span_start = self._span_stack.pop()
            duration_ms = (
                datetime.now(timezone.utc) - span_start
            ).total_seconds() * 1000
            self._events.append(
                TraceEvent(
                    timestamp=datetime.now(timezone.utc),
                    message=f"<<< {span_name}",
                    depth=self._current_depth,
                    kwargs={},
                    duration_ms=duration_ms,
                )
            )

    def set_user(self, user: "User") -> None:
        """Set user information after authentication."""
        self.user_id = str(user.id)
        self.user_email = user.email
        self.user_name = user.name

    def finalize(self) -> None:
        """Output the complete trace."""
        end_time = datetime.now(timezone.utc)
        total_duration_ms = (end_time - self.start_time).total_seconds() * 1000

        # Build output
        lines = [
            "=" * 80,
            f"TRACE SESSION: {self.session_id}",
            f"Request: {self.request_method} {self.request_path}",
        ]

        if self.user_email:
            lines.append(f"User: {self.user_email} (id={self.user_id})")
        else:
            lines.append("User: <unauthenticated>")

        lines.extend(
            [
                f"Client IP: {self.client_ip}",
                f"Duration: {total_duration_ms:.2f}ms",
                "-" * 80,
            ]
        )

        for event in self._events:
            indent = "  " * event.depth
            timestamp_str = event.timestamp.strftime("%H:%M:%S.%f")[:-3]

            # Format kwargs if present
            kwargs_parts = []
            for k, v in event.kwargs.items():
                # Truncate long values
                v_str = str(v)
                if len(v_str) > 100:
                    v_str = v_str[:97] + "..."
                kwargs_parts.append(f"{k}={v_str}")

            kwargs_str = ""
            if kwargs_parts:
                kwargs_str = " | " + ", ".join(kwargs_parts)

            # Add duration if present
            duration_str = ""
            if event.duration_ms is not None:
                duration_str = f" | duration_ms={event.duration_ms:.2f}"

            lines.append(
                f"[{timestamp_str}] {indent}{event.message}{kwargs_str}{duration_str}"
            )

        lines.append("=" * 80)

        # Print to stdout
        print("\n".join(lines))


class NoOpSession:
    """No-op session for when debug is disabled. Zero overhead."""

    def log(self, message: str, **kwargs: Any) -> None:
        pass

    @contextmanager
    def span(self, name: str) -> Generator[None, None, None]:  # type: ignore[override]
        yield

    def set_user(self, user: "User") -> None:
        pass

    def finalize(self) -> None:
        pass


class EventTracer:
    """Factory for creating trace sessions. Initialized from settings."""

    _instance: "EventTracer | None" = None

    def __init__(self) -> None:
        settings = get_settings()
        self._debug_enabled = settings.debug

    @classmethod
    def get_instance(cls) -> "EventTracer":
        """Get or create the singleton EventTracer."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. Useful for testing."""
        cls._instance = None

    @property
    def debug_enabled(self) -> bool:
        return self._debug_enabled

    def create_session(
        self,
        client_ip: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Session:
        """Create a new trace session."""
        if not self._debug_enabled:
            return NoOpSession()

        return ActiveSession(
            session_id=str(uuid4()),
            client_ip=client_ip,
            request_path=request_path,
            request_method=request_method,
            start_time=datetime.now(timezone.utc),
        )
