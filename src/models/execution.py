"""Execution state models for SpecForge pipeline runs."""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.models.cognitive_template import ExecutionTier


# ─── Enums ────────────────────────────────────────────────────────────────────


class ExecutionStatus(str, enum.Enum):
    """Overall status of an ExecutionRun."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatus(str, enum.Enum):
    """Per-node execution status."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED_TIER1 = "passed_tier1"
    PASSED_TIER2 = "passed_tier2"
    PASSED_TIER3 = "passed_tier3"
    FAILED = "failed"


# ─── Models ───────────────────────────────────────────────────────────────────


class ValidationResult(BaseModel):
    """Result of JSON Schema validation on a node's raw output.

    Attributes:
        is_valid: True if raw_output passed schema validation.
        errors: List of jsonschema validation error messages.
        raw_output: The unparsed string output from the node.
        parsed_output: Dict parsed from raw_output, if valid.
        validation_time_ms: Time spent validating in milliseconds.
    """

    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    raw_output: str = ""
    parsed_output: dict[str, Any] | None = None
    validation_time_ms: float = 0.0


class NodeResult(BaseModel):
    """Result of a single node's execution within an ExecutionRun.

    Attributes:
        node_id: ID of the node that executed.
        status: Final NodeStatus after all retry attempts.
        tier_used: Which ExecutionTier was used for this node.
        raw_output: Raw string output from the LLM/tool.
        parsed_output: Dict parsed from raw_output.
        validation_result: Outcome of JSON Schema validation.
        attempt_count: Number of attempts made (including retries).
        execution_time_ms: Wall-clock time in milliseconds.
        rule_files_used: List of rule .md file names injected as context.
        error_message: Error message string if status is FAILED.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str
    status: NodeStatus
    tier_used: ExecutionTier
    raw_output: str = ""
    parsed_output: dict[str, Any] | None = None
    validation_result: ValidationResult = Field(
        default_factory=lambda: ValidationResult(is_valid=False)
    )
    attempt_count: int = 0
    execution_time_ms: float = 0.0
    rule_files_used: list[str] = Field(default_factory=list)
    error_message: str | None = None


class ExecutionRun(BaseModel):
    """Complete execution state for a single Cognitive Template run.

    Attributes:
        run_id: UUID4 identifier for this execution.
        template_id: ID of the CognitiveTemplate being executed.
        template_name: Human-readable template name.
        status: Overall ExecutionStatus.
        input_data: Input payload passed to the template.
        node_results: Map of node_id -> NodeResult for all executed nodes.
        global_state: Accumulated key-value store from all node outputs.
        final_output: Final synthesized output after Result Weaver.
        started_at: UTC timestamp when execution began.
        completed_at: UTC timestamp when execution finished (None if not done).
        total_execution_time_ms: Total wall-clock time in milliseconds.
        error_message: Error message string if status is FAILED.
        state_file_path: Path to the generated state.md file, if any.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_encoders={datetime: lambda v: v.isoformat()},
    )

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    template_id: str = ""
    template_name: str = ""
    status: ExecutionStatus = ExecutionStatus.PENDING
    input_data: dict[str, Any] = Field(default_factory=dict)
    node_results: dict[str, NodeResult] = Field(default_factory=dict)
    global_state: dict[str, Any] = Field(default_factory=dict)
    final_output: dict[str, Any] | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    total_execution_time_ms: float | None = None
    error_message: str | None = None
    state_file_path: str | None = None
