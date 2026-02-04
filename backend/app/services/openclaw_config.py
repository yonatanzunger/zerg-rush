"""OpenClaw configuration generator service."""

import json
import secrets
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cloud.interfaces import SecretProvider
from app.models import Credential, AgentManifestStep, ManifestStepType, ManifestStepStatus

if TYPE_CHECKING:
    pass


@dataclass
class OpenClawConfigRequest:
    """Request to generate OpenClaw configuration."""

    agent_id: str
    user_id: str
    gateway_port: int = 18789
    model_primary: str = "anthropic/claude-opus-4-5"
    workspace_path: str = "~/.openclaw/workspace"
    enable_whatsapp: bool = False
    whatsapp_allow_from: list[str] | None = None


class OpenClawConfigGenerator:
    """Generates openclaw.json configuration for agents.

    This service is responsible for:
    - Generating the base configuration template
    - Mapping credentials to environment variables
    - Creating manifest steps based on required setup
    """

    # Mapping of credential types/names to OpenClaw environment variables
    CREDENTIAL_ENV_MAP = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "zai": "ZAI_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
        "brave": "BRAVE_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "firecrawl": "FIRECRAWL_API_KEY",
    }

    def __init__(self, secret_provider: SecretProvider, db: AsyncSession):
        self.secret_provider = secret_provider
        self.db = db

    async def generate_config(
        self,
        request: OpenClawConfigRequest,
        credential_ids: list[str],
    ) -> tuple[dict, dict[str, str]]:
        """Generate OpenClaw config template and env var mappings.

        Args:
            request: Configuration request with settings
            credential_ids: List of credential IDs to include

        Returns:
            Tuple of (config_dict, env_var_refs) where:
            - config_dict: The openclaw.json content (with ${VAR} placeholders)
            - env_var_refs: Mapping of VAR_NAME -> secret_ref
        """
        # Fetch credentials
        env_var_refs: dict[str, str] = {}
        if credential_ids:
            result = await self.db.execute(
                select(Credential).where(Credential.id.in_(credential_ids))
            )
            credentials = result.scalars().all()

            # Map credentials to environment variables
            for cred in credentials:
                env_var = self._credential_to_env_var(cred)
                if env_var:
                    env_var_refs[env_var] = cred.secret_ref

        # Generate gateway auth token
        gateway_token = secrets.token_urlsafe(32)
        gateway_token_ref = await self.secret_provider.store_secret(
            user_id=request.user_id,
            name=f"agent-{request.agent_id[:8]}-gateway-token",
            value=gateway_token,
        )
        env_var_refs["OPENCLAW_GATEWAY_TOKEN"] = gateway_token_ref

        # Build config template
        config = self._build_config_template(request, env_var_refs)

        return config, env_var_refs

    def _credential_to_env_var(self, credential: Credential) -> str | None:
        """Map a credential to its OpenClaw environment variable name."""
        # Check by credential name (case-insensitive)
        name_lower = credential.name.lower()
        for key, env_var in self.CREDENTIAL_ENV_MAP.items():
            if key in name_lower:
                return env_var

        # For LLM credentials, try to infer from description
        if credential.type == "llm":
            desc_lower = (credential.description or "").lower()
            for key, env_var in self.CREDENTIAL_ENV_MAP.items():
                if key in desc_lower:
                    return env_var
            # Default to Anthropic for unspecified LLM credentials
            return "ANTHROPIC_API_KEY"

        return None

    def _build_config_template(
        self,
        request: OpenClawConfigRequest,
        env_var_refs: dict[str, str],
    ) -> dict:
        """Build the OpenClaw configuration template."""
        config: dict = {
            "gateway": {
                "port": request.gateway_port,
                "auth": {
                    "mode": "token",
                    "token": "${OPENCLAW_GATEWAY_TOKEN}",
                },
            },
            "agents": {
                "defaults": {
                    "model": {
                        "primary": request.model_primary,
                    },
                    "workspace": request.workspace_path,
                },
            },
            "env": {},
        }

        # Add environment variable placeholders
        for env_var in env_var_refs:
            if env_var != "OPENCLAW_GATEWAY_TOKEN":
                config["env"][env_var] = f"${{{env_var}}}"

        # Add WhatsApp channel config if enabled
        if request.enable_whatsapp:
            config["channels"] = {
                "whatsapp": {}
            }
            if request.whatsapp_allow_from:
                config["channels"]["whatsapp"]["allowFrom"] = request.whatsapp_allow_from
            else:
                # Allow all if not specified
                config["channels"]["whatsapp"]["allowFrom"] = ["*"]

        return config

    async def resolve_config(
        self,
        config_template: dict,
        env_var_refs: dict[str, str],
    ) -> str:
        """Resolve placeholders in config and return final JSON5 string.

        Args:
            config_template: Config dict with ${VAR} placeholders
            env_var_refs: Mapping of VAR_NAME -> secret_ref

        Returns:
            JSON5 string with resolved values
        """
        # Fetch all secret values
        resolved_env_vars: dict[str, str] = {}
        for var_name, secret_ref in env_var_refs.items():
            value = await self.secret_provider.get_secret(secret_ref)
            resolved_env_vars[var_name] = value

        # Convert to JSON string and resolve placeholders
        config_str = json.dumps(config_template, indent=2)
        for var_name, value in resolved_env_vars.items():
            # Escape special JSON characters in the value
            escaped_value = json.dumps(value)[1:-1]  # Remove surrounding quotes
            config_str = config_str.replace(f"${{{var_name}}}", escaped_value)

        return config_str

    def generate_manifest_steps(
        self,
        request: OpenClawConfigRequest,
        credential_ids: list[str],
    ) -> list[AgentManifestStep]:
        """Generate required setup steps based on configuration.

        Args:
            request: Configuration request
            credential_ids: List of credential IDs

        Returns:
            List of manifest steps to be added to the agent
        """
        steps: list[AgentManifestStep] = []
        order = 0

        # Step 1: LLM credential verification (always required)
        steps.append(
            AgentManifestStep(
                step_type=ManifestStepType.CREDENTIAL_LLM.value,
                status=ManifestStepStatus.PENDING.value if not credential_ids else ManifestStepStatus.COMPLETED.value,
                order=order,
                config={"credential_ids": credential_ids},
            )
        )
        order += 1

        # Step 2: Gateway configuration
        steps.append(
            AgentManifestStep(
                step_type=ManifestStepType.CONFIG_GATEWAY.value,
                status=ManifestStepStatus.COMPLETED.value,  # Always auto-completed
                order=order,
                config={"port": request.gateway_port},
            )
        )
        order += 1

        # Step 3: WhatsApp pairing (if enabled)
        if request.enable_whatsapp:
            steps.append(
                AgentManifestStep(
                    step_type=ManifestStepType.CHANNEL_WHATSAPP.value,
                    status=ManifestStepStatus.PENDING.value,
                    order=order,
                    config={
                        "allow_from": request.whatsapp_allow_from,
                    },
                )
            )
            order += 1

        return steps

    def has_interactive_steps(self, request: OpenClawConfigRequest) -> bool:
        """Check if the configuration requires interactive setup steps."""
        return request.enable_whatsapp


@dataclass
class ResolvedConfig:
    """Fully resolved OpenClaw configuration ready for deployment."""

    config_json: str
    env_vars: dict[str, str]
    gateway_token: str
