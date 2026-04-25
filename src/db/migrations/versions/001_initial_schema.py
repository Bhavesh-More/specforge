"""Initial schema — creates all SpecForge tables.

Revision ID: 001
Revises:
Create Date: 2026-04-24 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── template_meta ─────────────────────────────────────────────────────────────
    op.create_table(
        "template_meta",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.String(20), nullable=False, server_default="1.0.0"),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("tags", JSON, nullable=False, server_default="[]"),
        sa.Column("file_path", sa.String(500), nullable=False),
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
            nullable=False,
        ),
    )

    # ── execution_runs ───────────────────────────────────────────────────────────
    op.create_table(
        "execution_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("template_meta.id"),
            nullable=False,
        ),
        sa.Column("template_name", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED",
                name="executionstatusenum",
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("input_data", JSON, nullable=False, server_default="{}"),
        sa.Column("final_output", JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_execution_time_ms", sa.Float, nullable=True),
        sa.Column("state_file_path", sa.String(500), nullable=True),
    )

    # ── node_results ─────────────────────────────────────────────────────────────
    op.create_table(
        "node_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("execution_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "RUNNING", "PASSED_TIER1", "PASSED_TIER2", "PASSED_TIER3", "FAILED",
                name="nodestatusenum",
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "tier_used",
            sa.Enum("FAST", "REPAIR", "DEEP", name="executiontierenum"),
            nullable=False,
            server_default="FAST",
        ),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "execution_time_ms", sa.Float, nullable=False, server_default="0.0"
        ),
        sa.Column(
            "validation_errors", JSON, nullable=False, server_default="[]"
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── healing_events ────────────────────────────────────────────────────────────
    op.create_table(
        "healing_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "trigger_type",
            sa.Enum(
                "CONSECUTIVE_FAILURES", "SCHEMA_MISMATCH", "LOGIC_ERROR",
                name="healingtriggerenum",
            ),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(100), nullable=False),
        sa.Column("template_id", sa.String(100), nullable=False),
        sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "failure_examples", JSON, nullable=False, server_default="[]"
        ),
        sa.Column("teacher_model", sa.String(100), nullable=False, server_default=""),
        sa.Column("patches", JSON, nullable=False, server_default="[]"),
        sa.Column("applied", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("healing_events")
    op.drop_table("node_results")
    op.drop_table("execution_runs")
    op.drop_table("template_meta")
