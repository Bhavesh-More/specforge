"""Self-healing loop models for SpecForge."""

import enum
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ────────────────────────────────────────────────────────────────────


class HealingTrigger(str, enum.Enum):
    """Reason the self-healing loop was triggered for a node."""

    CONSECUTIVE_FAILURES = "consecutive_failures"
    SCHEMA_MISMATCH = "schema_mismatch"
    LOGIC_ERROR = "logic_error"


# ─── Models ───────────────────────────────────────────────────────────────────


class RuleFilePatch(BaseModel):
    """A single semantic patch applied to a rule .md file.

    Attributes:
        file_name: Base name of the rule file (e.g. 'python_rules.md').
        original_content: The file content before patching.
        patched_content: The file content after patching.
        changes_summary: Human-readable summary of what changed.
        semantic_weights_applied: List of change labels applied
            (e.g. 'moved_critical_rule_to_top', 'added_negative_example').
    """

    model_config = ConfigDict(extra="forbid")

    file_name: str
    original_content: str = ""
    patched_content: str = ""
    changes_summary: str = ""
    semantic_weights_applied: list[str] = Field(default_factory=list)


class HealingEvent(BaseModel):
    """A self-healing event for a specific node within a template.

    Attributes:
        event_id: UUID4 identifier for this healing event.
        triggered_at: UTC timestamp when healing was triggered.
        trigger: Which condition triggered the healing loop.
        node_id: ID of the node that failed.
        template_id: ID of the template containing the failed node.
        failure_count: Number of consecutive failures before healing fired.
        failure_examples: List of raw failed output strings for context.
        teacher_model_used: Name of the teacher model consulted.
        patches: List of RuleFilePatch objects to apply.
        applied: Whether these patches have been applied to the rules.
        applied_at: UTC timestamp when patches were applied (None if not yet).
        approved_by: Human approver identifier (for audit trail).
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_encoders={datetime: lambda v: v.isoformat()},
    )

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trigger: HealingTrigger
    node_id: str = ""
    template_id: str = ""
    failure_count: int = 0
    failure_examples: list[str] = Field(default_factory=list)
    teacher_model_used: str = ""
    patches: list[RuleFilePatch] = Field(default_factory=list)
    applied: bool = False
    applied_at: datetime | None = None
    approved_by: str | None = None
