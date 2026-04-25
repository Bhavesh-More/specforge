"""SQLAlchemy 2.0 ORM models for SpecForge persistence layer."""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy import Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 DeclarativeBase for all ORM models."""
    pass


class ExecutionStatusEnum(str, PyEnum):
    """Execution run status enum."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatusEnum(str, PyEnum):
    """Node execution status enum."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED_TIER1 = "passed_tier1"
    PASSED_TIER2 = "passed_tier2"
    PASSED_TIER3 = "passed_tier3"
    FAILED = "failed"


class ExecutionTierEnum(str, PyEnum):
    """Execution tier enum."""
    FAST = "fast"
    REPAIR = "repair"
    DEEP = "deep"


class HealingTriggerEnum(str, PyEnum):
    """Healing trigger type enum."""
    CONSECUTIVE_FAILURES = "consecutive_failures"
    SCHEMA_MISMATCH = "schema_mismatch"
    LOGIC_ERROR = "logic_error"


# ─── Models ────────────────────────────────────────────────────────────────────


class TemplateMetaDB(Base):
    """Template metadata stored in PostgreSQL (full JSON on disk).

    Attributes:
        id: UUID primary key matching template_id in .ct.json.
        name: Human-readable template name.
        version: Semver version string.
        description: Brief description.
        tags: JSON list of tag strings.
        file_path: Path to the .ct.json file on disk.
        created_at: UTC creation timestamp.
        updated_at: UTC last modification timestamp.
    """

    __tablename__ = "template_meta"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    execution_runs: Mapped[list["ExecutionRunDB"]] = relationship(
        "ExecutionRunDB", back_populates="template", lazy="selectin"
    )


class ExecutionRunDB(Base):
    """A single execution run record.

    Attributes:
        id: UUID primary key matching run_id.
        template_id: Foreign key to TemplateMetaDB.
        template_name: Denormalized template name for convenience.
        status: Current execution status.
        input_data: JSON payload passed to the template.
        final_output: JSON final assembled output (nullable until complete).
        error_message: Error message string if failed.
        started_at: UTC start timestamp.
        completed_at: UTC completion timestamp (nullable).
        total_execution_time_ms: Total wall-clock time in ms (nullable).
        state_file_path: Path to the generated state.md file.
    """

    __tablename__ = "execution_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("template_meta.id"), nullable=False
    )
    template_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[ExecutionStatusEnum] = mapped_column(
        Enum(ExecutionStatusEnum), nullable=False, default=ExecutionStatusEnum.PENDING
    )
    input_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    final_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_execution_time_ms: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    state_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    template: Mapped["TemplateMetaDB"] = relationship(
        "TemplateMetaDB", back_populates="execution_runs"
    )
    node_results: Mapped[list["NodeResultDB"]] = relationship(
        "NodeResultDB", back_populates="run", cascade="all, delete-orphan"
    )


class NodeResultDB(Base):
    """Per-node result for an execution run.

    Attributes:
        id: UUID primary key.
        run_id: Foreign key to ExecutionRunDB.
        node_id: ID of the DAG node that executed.
        status: Final node status after all attempts.
        tier_used: Which execution tier was used.
        attempt_count: Number of attempts made.
        execution_time_ms: Wall-clock time in ms.
        validation_errors: JSON list of validation error strings.
        error_message: Error message if failed.
        created_at: Timestamp when result was recorded.
    """

    __tablename__ = "node_results"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("execution_runs.id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[NodeStatusEnum] = mapped_column(
        Enum(NodeStatusEnum), nullable=False, default=NodeStatusEnum.PENDING
    )
    tier_used: Mapped[ExecutionTierEnum] = mapped_column(
        Enum(ExecutionTierEnum), nullable=False, default=ExecutionTierEnum.FAST
    )
    attempt_count: Mapped[int] = mapped_column(default=0)
    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    validation_errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    run: Mapped["ExecutionRunDB"] = relationship(
        "ExecutionRunDB", back_populates="node_results"
    )


class HealingEventDB(Base):
    """A self-healing event record.

    Attributes:
        id: UUID primary key.
        triggered_at: UTC timestamp when healing was triggered.
        trigger_type: Which condition triggered the healing.
        node_id: ID of the node that failed.
        template_id: ID of the template containing the node.
        failure_count: Number of consecutive failures before healing.
        failure_examples: JSON list of raw failed output strings.
        teacher_model: Name of the teacher model consulted.
        patches: JSON list of RuleFilePatch dicts.
        applied: Whether patches have been applied.
        applied_at: UTC timestamp when patches were applied.
        approved_by: Human approver identifier.
    """

    __tablename__ = "healing_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    trigger_type: Mapped[HealingTriggerEnum] = mapped_column(
        Enum(HealingTriggerEnum), nullable=False
    )
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    template_id: Mapped[str] = mapped_column(String(100), nullable=False)
    failure_count: Mapped[int] = mapped_column(default=0)
    failure_examples: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    teacher_model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    patches: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
