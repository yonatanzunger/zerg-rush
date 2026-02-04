"""Agent platform implementations.

This module provides abstract base classes and concrete implementations
for different agent platforms (e.g., OpenClaw, Claude Code).
"""

from app.agents.base import AgentPlatform, PlatformConfig
from app.agents.factory import (
    get_platform,
    get_available_platforms,
    register_platform,
)
from app.agents.openclaw import OpenClawPlatform

__all__ = [
    # Base classes
    "AgentPlatform",
    "PlatformConfig",
    # Factory functions
    "get_platform",
    "get_available_platforms",
    "register_platform",
    # Platform implementations
    "OpenClawPlatform",
]
