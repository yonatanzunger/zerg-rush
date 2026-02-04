"""Add hatching models: manifest steps, agent config, channel credentials.

Revision ID: 20260204_000002
Revises: 20260204_000001
Create Date: 2026-02-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260204_000002"
down_revision: Union[str, None] = "20260204_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create agent_manifest_steps table
    op.create_table(
        "agent_manifest_steps",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("active_agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("order", sa.Integer, server_default="0"),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_manifest_steps_agent_id",
        "agent_manifest_steps",
        ["agent_id"],
    )

    # Create agent_configs table
    op.create_table(
        "agent_configs",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("active_agents.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("config_template", sa.JSON, nullable=False),
        sa.Column("gateway_port", sa.Integer, server_default="18789"),
        sa.Column("gateway_auth_token_ref", sa.String(255), nullable=True),
        sa.Column(
            "workspace_path",
            sa.String(255),
            server_default="~/.openclaw/workspace",
        ),
        sa.Column("enabled_channels", sa.JSON, server_default="[]"),
        sa.Column("env_var_refs", sa.JSON, server_default="{}"),
        sa.Column("model_primary", sa.String(100), nullable=True),
        sa.Column("whatsapp_allow_from", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # Create channel_credentials table
    op.create_table(
        "channel_credentials",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("active_agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_type", sa.String(50), nullable=False),
        sa.Column("account_id", sa.String(255), nullable=True),
        sa.Column("credentials_secret_ref", sa.String(255), nullable=False),
        sa.Column("is_paired", sa.Boolean, server_default="false"),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_channel_credentials_agent_id",
        "channel_credentials",
        ["agent_id"],
    )

    # Add columns to active_agents
    op.add_column(
        "active_agents",
        sa.Column("hatching_status", sa.String(20), server_default="pending"),
    )
    op.add_column(
        "active_agents",
        sa.Column("config_version", sa.Integer, server_default="1"),
    )

    # Add columns to saved_agents
    op.add_column(
        "saved_agents",
        sa.Column("manifest_snapshot", sa.JSON, nullable=True),
    )
    op.add_column(
        "saved_agents",
        sa.Column("channel_credentials_refs", sa.JSON, nullable=True),
    )
    op.add_column(
        "saved_agents",
        sa.Column("config_template_snapshot", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    # Remove columns from saved_agents
    op.drop_column("saved_agents", "config_template_snapshot")
    op.drop_column("saved_agents", "channel_credentials_refs")
    op.drop_column("saved_agents", "manifest_snapshot")

    # Remove columns from active_agents
    op.drop_column("active_agents", "config_version")
    op.drop_column("active_agents", "hatching_status")

    # Drop tables
    op.drop_index("ix_channel_credentials_agent_id", "channel_credentials")
    op.drop_table("channel_credentials")
    op.drop_table("agent_configs")
    op.drop_index("ix_agent_manifest_steps_agent_id", "agent_manifest_steps")
    op.drop_table("agent_manifest_steps")
