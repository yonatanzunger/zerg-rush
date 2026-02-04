"""OpenClaw agent platform implementation."""

from app.agents.base import AgentPlatform


class OpenClawPlatform(AgentPlatform):
    """OpenClaw agent platform.

    OpenClaw is a Node.js-based agent platform that runs on pnpm.
    """

    @property
    def platform_type(self) -> str:
        return "openclaw"

    def get_startup_script(self, version: str | None = None) -> str:
        """Get the startup script for OpenClaw platform.

        Args:
            version: Optional specific version to install. If None, installs latest.

        Returns:
            Bash startup script that installs Node.js, pnpm, and OpenClaw.
        """
        version_spec = f"openclaw@{version}" if version else "openclaw@latest"

        return f"""#!/bin/bash
set -e

# Update system
apt-get update
apt-get install -y curl

# Install Node.js 22
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

# Install pnpm
npm install -g pnpm

# Install openclaw
pnpm add -g {version_spec}

# Create openclaw user
useradd -m -s /bin/bash openclaw || true

# Create config directory
sudo -u openclaw mkdir -p /home/openclaw/.openclaw

# Signal that setup is complete
touch /home/openclaw/.openclaw/setup-complete
"""

    def get_health_check_command(self) -> str | None:
        """Check if OpenClaw setup is complete."""
        return "test -f /home/openclaw/.openclaw/setup-complete"

    def get_default_gateway_port(self) -> int:
        return 8080
