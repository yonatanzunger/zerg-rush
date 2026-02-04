"""Agent manifest service for managing setup steps."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActiveAgent,
    AgentManifestStep,
    ManifestStepStatus,
    ManifestStepType,
    HatchingStatus,
)


class AgentManifestService:
    """Manages agent setup manifests.

    The manifest tracks all required setup steps for an agent,
    including credentials, channel pairing, and configuration.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_manifest(
        self,
        agent_id: str,
        steps: list[AgentManifestStep],
    ) -> list[AgentManifestStep]:
        """Create manifest steps for a new agent.

        Args:
            agent_id: The agent ID
            steps: List of manifest steps to create

        Returns:
            The created manifest steps
        """
        for step in steps:
            step.agent_id = agent_id
            self.db.add(step)

        await self.db.flush()
        return steps

    async def get_all_steps(self, agent_id: str) -> list[AgentManifestStep]:
        """Get all manifest steps for an agent.

        Args:
            agent_id: The agent ID

        Returns:
            List of all manifest steps, ordered by order field
        """
        result = await self.db.execute(
            select(AgentManifestStep)
            .where(AgentManifestStep.agent_id == agent_id)
            .order_by(AgentManifestStep.order)
        )
        return list(result.scalars().all())

    async def get_pending_steps(self, agent_id: str) -> list[AgentManifestStep]:
        """Get all pending manifest steps for an agent.

        Args:
            agent_id: The agent ID

        Returns:
            List of pending manifest steps
        """
        result = await self.db.execute(
            select(AgentManifestStep)
            .where(
                AgentManifestStep.agent_id == agent_id,
                AgentManifestStep.status == ManifestStepStatus.PENDING.value,
            )
            .order_by(AgentManifestStep.order)
        )
        return list(result.scalars().all())

    async def get_interactive_pending_steps(
        self, agent_id: str
    ) -> list[AgentManifestStep]:
        """Get pending steps that require user interaction.

        Args:
            agent_id: The agent ID

        Returns:
            List of interactive pending steps
        """
        interactive_types = [
            ManifestStepType.CHANNEL_WHATSAPP.value,
            ManifestStepType.CHANNEL_TELEGRAM.value,
            ManifestStepType.CHANNEL_DISCORD.value,
        ]
        result = await self.db.execute(
            select(AgentManifestStep)
            .where(
                AgentManifestStep.agent_id == agent_id,
                AgentManifestStep.status == ManifestStepStatus.PENDING.value,
                AgentManifestStep.step_type.in_(interactive_types),
            )
            .order_by(AgentManifestStep.order)
        )
        return list(result.scalars().all())

    async def get_step_by_id(self, step_id: str) -> AgentManifestStep | None:
        """Get a specific manifest step by ID.

        Args:
            step_id: The step ID

        Returns:
            The manifest step or None if not found
        """
        result = await self.db.execute(
            select(AgentManifestStep).where(AgentManifestStep.id == step_id)
        )
        return result.scalar_one_or_none()

    async def get_step_by_type(
        self, agent_id: str, step_type: str
    ) -> AgentManifestStep | None:
        """Get a manifest step by type for an agent.

        Args:
            agent_id: The agent ID
            step_type: The step type

        Returns:
            The manifest step or None if not found
        """
        result = await self.db.execute(
            select(AgentManifestStep).where(
                AgentManifestStep.agent_id == agent_id,
                AgentManifestStep.step_type == step_type,
            )
        )
        return result.scalar_one_or_none()

    async def complete_step(
        self,
        step_id: str,
        result: dict | None = None,
    ) -> AgentManifestStep:
        """Mark a manifest step as completed.

        Args:
            step_id: The step ID
            result: Optional result data to store

        Returns:
            The updated manifest step

        Raises:
            ValueError: If step not found
        """
        step = await self.get_step_by_id(step_id)
        if not step:
            raise ValueError(f"Manifest step {step_id} not found")

        step.status = ManifestStepStatus.COMPLETED.value
        step.completed_at = datetime.now(timezone.utc)
        if result:
            step.result = result

        await self.db.flush()
        return step

    async def fail_step(
        self,
        step_id: str,
        error_message: str,
    ) -> AgentManifestStep:
        """Mark a manifest step as failed.

        Args:
            step_id: The step ID
            error_message: The error message

        Returns:
            The updated manifest step

        Raises:
            ValueError: If step not found
        """
        step = await self.get_step_by_id(step_id)
        if not step:
            raise ValueError(f"Manifest step {step_id} not found")

        step.status = ManifestStepStatus.FAILED.value
        step.error_message = error_message

        await self.db.flush()
        return step

    async def start_step(self, step_id: str) -> AgentManifestStep:
        """Mark a manifest step as in progress.

        Args:
            step_id: The step ID

        Returns:
            The updated manifest step

        Raises:
            ValueError: If step not found
        """
        step = await self.get_step_by_id(step_id)
        if not step:
            raise ValueError(f"Manifest step {step_id} not found")

        step.status = ManifestStepStatus.IN_PROGRESS.value

        await self.db.flush()
        return step

    async def is_hatching_complete(self, agent_id: str) -> bool:
        """Check if all required setup steps are completed.

        Args:
            agent_id: The agent ID

        Returns:
            True if all required steps are completed or skipped
        """
        result = await self.db.execute(
            select(AgentManifestStep).where(
                AgentManifestStep.agent_id == agent_id,
                AgentManifestStep.status.in_([
                    ManifestStepStatus.PENDING.value,
                    ManifestStepStatus.IN_PROGRESS.value,
                ]),
            )
        )
        pending_steps = result.scalars().all()
        return len(pending_steps) == 0

    async def update_agent_hatching_status(self, agent_id: str) -> HatchingStatus:
        """Update the agent's hatching status based on manifest state.

        Args:
            agent_id: The agent ID

        Returns:
            The new hatching status
        """
        result = await self.db.execute(
            select(ActiveAgent).where(ActiveAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        # Check for failed steps
        failed_result = await self.db.execute(
            select(AgentManifestStep).where(
                AgentManifestStep.agent_id == agent_id,
                AgentManifestStep.status == ManifestStepStatus.FAILED.value,
            )
        )
        if failed_result.scalars().first():
            agent.hatching_status = HatchingStatus.FAILED.value
            await self.db.flush()
            return HatchingStatus.FAILED

        # Check if complete
        if await self.is_hatching_complete(agent_id):
            agent.hatching_status = HatchingStatus.COMPLETED.value
            await self.db.flush()
            return HatchingStatus.COMPLETED

        # Check for in-progress steps
        in_progress_result = await self.db.execute(
            select(AgentManifestStep).where(
                AgentManifestStep.agent_id == agent_id,
                AgentManifestStep.status == ManifestStepStatus.IN_PROGRESS.value,
            )
        )
        if in_progress_result.scalars().first():
            agent.hatching_status = HatchingStatus.IN_PROGRESS.value
            await self.db.flush()
            return HatchingStatus.IN_PROGRESS

        # Default to pending
        agent.hatching_status = HatchingStatus.PENDING.value
        await self.db.flush()
        return HatchingStatus.PENDING

    async def get_manifest_snapshot(self, agent_id: str) -> dict:
        """Get manifest state for saving to a template.

        Args:
            agent_id: The agent ID

        Returns:
            Dictionary snapshot of the manifest
        """
        steps = await self.get_all_steps(agent_id)
        return {
            "steps": [
                {
                    "step_type": step.step_type,
                    "status": step.status,
                    "order": step.order,
                    "config": step.config,
                    "result": step.result,
                    "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                }
                for step in steps
            ]
        }

    async def restore_from_snapshot(
        self,
        agent_id: str,
        snapshot: dict,
    ) -> list[AgentManifestStep]:
        """Restore manifest from a saved snapshot.

        Args:
            agent_id: The new agent ID
            snapshot: The manifest snapshot from a saved agent

        Returns:
            List of created manifest steps
        """
        steps = []
        for step_data in snapshot.get("steps", []):
            step = AgentManifestStep(
                agent_id=agent_id,
                step_type=step_data["step_type"],
                # Completed steps stay completed, others reset to pending
                status=(
                    step_data["status"]
                    if step_data["status"] == ManifestStepStatus.COMPLETED.value
                    else ManifestStepStatus.PENDING.value
                ),
                order=step_data["order"],
                config=step_data.get("config"),
                # Only preserve result if step was completed
                result=(
                    step_data.get("result")
                    if step_data["status"] == ManifestStepStatus.COMPLETED.value
                    else None
                ),
            )
            self.db.add(step)
            steps.append(step)

        await self.db.flush()
        return steps
