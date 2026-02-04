"""OpenClaw agent platform implementation."""

from app.agents.base import AgentPlatform
from app.models.user import User


class OpenClawPlatform(AgentPlatform):
    """OpenClaw agent platform.

    OpenClaw is a Node.js-based agent platform that runs on pnpm.
    """

    @property
    def platform_type(self) -> str:
        return "openclaw"

    def get_startup_script(self, user: "User", version: str | None = None) -> str:
        """Get the startup script for OpenClaw platform.

        Args:
            user: The current user requesting the agent.
            version: Optional specific version to install. If None, installs latest.

        Returns:
            Bash startup script that installs Node.js, pnpm, and OpenClaw.
        """
        # TODO: Need to implement the actual openclaw onboarding logic, including
        # getting the appropriate keys from the LLM, setting up the config, etc.,
        # and then starting the server. It may make sense to construct the json
        # file locally in the server and ship it over.

        return f"""#!/bin/bash
set -e

# Update system
apt-get update
apt-get install -y curl

# Install Node.js 22
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

# Make sure the user is ready to go
useradd -m -s /bin/bash {user.name} || true

# Switch to user context
sudo -u {user.name} bash << 'EOF'
  cd ~
  # Install pnpm
  curl -fsSL https://get.pnpm.io/install.sh | sh -"
  export PNPM_HOME="$HOME/.local/share/pnpm"
  export PATH="$PNPM_HOME:$PATH"
  # Install openclaw
  curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-prompt --install-method npm --no-onboard
EOF
"""

    def get_health_check_command(self) -> str | None:
        """Check if OpenClaw setup is complete."""
        return "test -f /home/openclaw/.openclaw/setup-complete"

    def get_default_gateway_port(self) -> int:
        return 8080
