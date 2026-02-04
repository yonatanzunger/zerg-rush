"""Factory for creating agent platform instances."""

from app.agents.base import AgentPlatform
from app.agents.openclaw import OpenClawPlatform


# Registry of available platforms
_PLATFORMS: dict[str, type[AgentPlatform]] = {
    "openclaw": OpenClawPlatform,
}

# Cache of instantiated platforms (they're stateless so we can reuse them)
_platform_instances: dict[str, AgentPlatform] = {}


def get_platform(platform_type: str) -> AgentPlatform:
    """Get an agent platform instance by type.

    Args:
        platform_type: The platform type identifier (e.g., 'openclaw').

    Returns:
        An AgentPlatform instance for the requested type.

    Raises:
        ValueError: If the platform type is not recognized.
    """
    if platform_type not in _PLATFORMS:
        available = ", ".join(sorted(_PLATFORMS.keys()))
        raise ValueError(
            f"Unknown platform type: {platform_type}. Available: {available}"
        )

    # Return cached instance or create new one
    if platform_type not in _platform_instances:
        _platform_instances[platform_type] = _PLATFORMS[platform_type]()

    return _platform_instances[platform_type]


def get_available_platforms() -> list[str]:
    """Get a list of available platform types."""
    return list(_PLATFORMS.keys())


def register_platform(platform_type: str, platform_class: type[AgentPlatform]) -> None:
    """Register a new platform type.

    This can be used to add custom platforms at runtime.

    Args:
        platform_type: The platform type identifier.
        platform_class: The AgentPlatform subclass to register.
    """
    _PLATFORMS[platform_type] = platform_class
    # Clear cached instance if it exists
    _platform_instances.pop(platform_type, None)
