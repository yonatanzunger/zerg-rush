"""Add vm_external_ip, vm_zone, and cloud_provider columns to active_agents.

Revision ID: 20260204_000001
Revises: 20250203_000001
Create Date: 2026-02-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260204_000001"
down_revision: Union[str, None] = "20250203_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "active_agents",
        sa.Column("vm_external_ip", sa.String(45), nullable=True),
    )
    op.add_column(
        "active_agents",
        sa.Column("vm_zone", sa.String(100), nullable=True),
    )
    op.add_column(
        "active_agents",
        sa.Column("cloud_provider", sa.String(20), nullable=False, server_default="gcp"),
    )


def downgrade() -> None:
    op.drop_column("active_agents", "cloud_provider")
    op.drop_column("active_agents", "vm_zone")
    op.drop_column("active_agents", "vm_external_ip")
