"""Event tracing system for debugging request flows and streaming updates."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, ContextManager, Generator, Protocol
from uuid import uuid4
import traceback

from app.config import get_settings
from app.models import User

# If set to True, this will dump out detailed tracebacks into the trace log when
# exceptions occur within traced functions. This is useful for debugging but may
# expose sensitive information, so it should be used with caution.
SHOW_TRACES_ON_ERROR = True


@dataclass
class TraceEvent:
    """A single trace event in the session."""

    timestamp: datetime
    message: str
    depth: int
    kwargs: dict[str, Any]
    duration_ms: float | None = None


@dataclass
class StreamEvent:
    """An event formatted for streaming to the frontend."""

    type: str  # "log", "span_start", "span_end", "complete", "error"
    timestamp: datetime
    message: str
    depth: int = 0
    data: dict[str, Any] | None = None
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary for JSON serialization."""
        result = {
            "type": self.type,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "depth": self.depth,
        }
        if self.data:
            result["data"] = self.data
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        return result


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

    def enable_streaming(self) -> None:
        """Enable streaming mode for this session."""
        ...

    def finish_streaming(self, error: str | None = None) -> None:
        """Signal the end of streaming, optionally with an error."""
        ...

    def emit_completion(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Emit a completion event and finish streaming."""
        ...

    def stream_events(self) -> AsyncGenerator[StreamEvent, None]:
        """Yield events as they are logged. Must call enable_streaming() first."""
        ...


class FunctionTrace(ContextManager[None]):
    """Context manager for tracing a function execution."""

    def __init__(self, session: Session | None, message: str, **kwargs: Any) -> None:
        self._session = session
        self._message = message
        self._kwargs = kwargs

    def __enter__(self) -> None:
        self.log(self._message, _indent="", **self._kwargs)
        return self

    def __exit__(self, exc_type, exc_value, tb) -> None:
        if exc_type is not None and self._session is not None:
            self.log(f"Exception in {self._message}: {exc_value}")
            if SHOW_TRACES_ON_ERROR:
                trace = traceback.extract_tb(tb)
                for frame in trace:
                    self.log(f"  {frame.filename}:{frame.lineno} in {frame.name}")

    def log(self, message: str, _indent: str = "  ", **kwargs: Any) -> None:
        """Log an event within the function trace."""
        if self._session is not None:
            self._session.log(_indent + message, **kwargs)


@dataclass
class ActiveSession:
    """Active trace session that captures events."""

    session_id: str
    client_ip: str | None
    request_path: str | None
    request_method: str | None
    start_time: datetime
    debug: bool = False  # If True, also print to console
    user_id: str | None = None
    user_email: str | None = None
    user_name: str | None = None
    _events: list[TraceEvent] = field(default_factory=list)
    _current_depth: int = 0
    _span_stack: list[tuple[str, datetime]] = field(default_factory=list)
    _streaming: bool = False
    _event_queue: asyncio.Queue[StreamEvent | None] = field(default_factory=asyncio.Queue)

    def enable_streaming(self) -> None:
        """Enable streaming mode for this session."""
        self._streaming = True

    def finish_streaming(self, error: str | None = None) -> None:
        """Signal the end of streaming, optionally with an error."""
        if error:
            self._event_queue.put_nowait(
                StreamEvent(
                    type="error",
                    timestamp=datetime.now(timezone.utc),
                    message=error,
                    depth=0,
                )
            )
        else:
            self._event_queue.put_nowait(None)  # Sentinel to signal end

    async def stream_events(self) -> AsyncGenerator[StreamEvent, None]:
        """Yield events as they are logged. Must call enable_streaming() first."""
        while True:
            event = await self._event_queue.get()
            if event is None:  # End sentinel
                break
            yield event

    def emit_completion(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Emit a completion event and finish streaming."""
        self._event_queue.put_nowait(
            StreamEvent(
                type="complete",
                timestamp=datetime.now(timezone.utc),
                message=message,
                data=data,
            )
        )
        self.finish_streaming()

    def _emit_stream_event(self, event: StreamEvent) -> None:
        """Emit an event to the stream queue if streaming is enabled."""
        if self._streaming:
            self._event_queue.put_nowait(event)

        # Print to console if debug mode is enabled
        if self.debug:
            self._print_stream_event(event)

    def _print_stream_event(self, event: StreamEvent) -> None:
        """Print a stream event to console."""
        indent = "  " * event.depth
        timestamp_str = event.timestamp.strftime("%H:%M:%S.%f")[:-3]
        data_str = ""
        if event.data:
            data_parts = [f"{k}={v}" for k, v in event.data.items()]
            data_str = " | " + ", ".join(data_parts)
        duration_str = ""
        if event.duration_ms is not None:
            duration_str = f" | {event.duration_ms:.0f}ms"
        print(f"[{timestamp_str}] {indent}{event.message}{data_str}{duration_str}")

    def log(self, message: str, **kwargs: Any) -> None:
        """Log an event at the current nesting depth."""
        now = datetime.now(timezone.utc)
        self._events.append(
            TraceEvent(
                timestamp=now,
                message=message,
                depth=self._current_depth,
                kwargs=kwargs,
            )
        )
        # Emit to stream
        self._emit_stream_event(
            StreamEvent(
                type="log",
                timestamp=now,
                message=message,
                depth=self._current_depth,
                data=kwargs if kwargs else None,
            )
        )

    @contextmanager
    def span(self, name: str) -> Generator[None, None, None]:  # type: ignore[override]
        """Create a nested span for hierarchical tracing."""
        start_time = datetime.now(timezone.utc)
        self._span_stack.append((name, start_time))

        # Log span start
        self._events.append(
            TraceEvent(
                timestamp=start_time,
                message=f">>> {name}",
                depth=self._current_depth,
                kwargs={},
            )
        )
        self._emit_stream_event(
            StreamEvent(
                type="span_start",
                timestamp=start_time,
                message=name,
                depth=self._current_depth,
            )
        )
        self._current_depth += 1

        try:
            yield
        finally:
            self._current_depth -= 1
            span_name, span_start = self._span_stack.pop()
            end_time = datetime.now(timezone.utc)
            duration_ms = (end_time - span_start).total_seconds() * 1000
            self._events.append(
                TraceEvent(
                    timestamp=end_time,
                    message=f"<<< {span_name}",
                    depth=self._current_depth,
                    kwargs={},
                    duration_ms=duration_ms,
                )
            )
            self._emit_stream_event(
                StreamEvent(
                    type="span_end",
                    timestamp=end_time,
                    message=span_name,
                    depth=self._current_depth,
                    duration_ms=duration_ms,
                )
            )

    def set_user(self, user: "User") -> None:
        """Set user information after authentication."""
        self.user_id = str(user.id)
        self.user_email = user.email
        self.user_name = user.name

    def finalize(self) -> None:
        """Output the complete trace if debug is enabled.

        For streaming sessions, this is typically not called as events are
        streamed in real-time. This is mainly for non-streaming debug output.
        """
        # Only print full trace summary in debug mode and when not streaming
        # (streaming sessions already emit events in real-time)
        if not self.debug or self._streaming:
            return

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
    """No-op session for non-streaming operations. Zero overhead."""

    def log(self, message: str, **kwargs: Any) -> None:
        pass

    @contextmanager
    def span(self, name: str) -> Generator[None, None, None]:  # type: ignore[override]
        yield

    def set_user(self, user: "User") -> None:
        pass

    def finalize(self) -> None:
        pass

    def enable_streaming(self) -> None:
        pass

    def finish_streaming(self, error: str | None = None) -> None:
        pass

    def emit_completion(self, message: str, data: dict[str, Any] | None = None) -> None:
        pass

    async def stream_events(self) -> AsyncGenerator[StreamEvent, None]:
        # Empty generator - yields nothing
        return
        yield  # Make this a generator


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
        """Create a new trace session.

        For non-streaming requests, returns NoOpSession when debug is disabled,
        or ActiveSession with debug=True when debug is enabled.
        """
        if not self._debug_enabled:
            return NoOpSession()

        return ActiveSession(
            session_id=str(uuid4()),
            client_ip=client_ip,
            request_path=request_path,
            request_method=request_method,
            start_time=datetime.now(timezone.utc),
            debug=True,  # Print to console when debug is enabled
        )

    def create_streaming_session(
        self,
        client_ip: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ActiveSession:
        """Create a new streaming session.

        Always returns an ActiveSession with streaming enabled.
        The debug flag controls whether events are also printed to console.
        """
        session = ActiveSession(
            session_id=str(uuid4()),
            client_ip=client_ip,
            request_path=request_path,
            request_method=request_method,
            start_time=datetime.now(timezone.utc),
            debug=self._debug_enabled,  # Also print to console if debug is enabled
        )
        session.enable_streaming()
        return session
