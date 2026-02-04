"""Abstract base class for agent platforms."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User


@dataclass
class PlatformConfig:
    """Configuration for an agent platform."""

    platform_type: str
    version: str | None = None
    # Additional config options can be added by subclasses


@dataclass
class StartupScriptConfig:
    """Configuration for generating a startup script with credentials.

    This is used to pass credential bundle information to the startup script
    so the VM can download and decrypt the configuration on boot.
    """

    bundle_url: str | None = None
    decryption_key: str | None = None
    gateway_port: int = 18789


class AgentPlatform(ABC):
    """Abstract base class for agent platform implementations.

    Each agent platform (e.g., OpenClaw, Claude Code) should implement
    this interface to provide platform-specific setup and configuration.
    """

    @property
    @abstractmethod
    def platform_type(self) -> str:
        """Return the platform type identifier (e.g., 'openclaw')."""
        ...

    @property
    def default_version(self) -> str | None:
        """Return the default version for this platform, if applicable."""
        return None

    @abstractmethod
    def get_startup_script(
        self,
        user: "User",
        version: str | None = None,
        config: StartupScriptConfig | None = None,
    ) -> str:
        """Get the VM startup script for this platform.

        Args:
            user: The current user requesting the agent.
            version: Optional specific version to install. If None, uses latest.
            config: Optional startup script configuration with bundle URL and key.

        Returns:
            Bash startup script to configure the VM for this platform.
        """
        ...

    def get_health_check_command(self) -> str | None:
        """Get a command to check if the platform is ready.

        Returns:
            A shell command that exits 0 when the platform is ready,
            or None if no health check is available.
        """
        return None

    def get_default_gateway_port(self) -> int:
        """Get the default gateway port for this platform."""
        return 8080

    def validate_config(self, config: PlatformConfig) -> list[str]:
        """Validate platform-specific configuration.

        Args:
            config: Platform configuration to validate.

        Returns:
            List of validation error messages, empty if valid.
        """
        errors = []
        if config.platform_type != self.platform_type:
            errors.append(
                f"Config platform_type '{config.platform_type}' "
                f"does not match platform '{self.platform_type}'"
            )
        return errors
