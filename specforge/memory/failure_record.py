"""Failure Memory Bank record model."""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class FailureType(str, Enum):
    """Taxonomy of LLM node failures used for proactive adaptation."""

    SCHEMA_VIOLATION = "schema_violation"
    HALLUCINATION_DRIFT = "hallucination_drift"
    PREMATURE_CONCLUSION = "premature_conclusion"
    LOGICAL_CONTRADICTION = "logical_contradiction"
    CONTEXT_FORGETTING = "context_forgetting"
    OVER_GENERATION = "over_generation"
    TOOL_MISUSE = "tool_misuse"
    UNKNOWN = "unknown"


@dataclass
class CognitiveFailureRecord:
    """A complete record of one failed node execution."""

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    node_type: str = ""
    task_description: str = ""
    model_used: str = ""

    failure_type: FailureType = FailureType.UNKNOWN
    validator_error: str = ""
    failed_output: str = ""
    entropy_at_failure: float = 0.0

    repair_attempted: bool = False
    repair_strategy_used: str = ""
    repair_successful: bool = False
    successful_output: str = ""
    repair_prompt_delta: str = ""

    recommended_spa_threshold: Optional[float] = None
    recommended_n_drafts: Optional[int] = None
    recommended_prompt_prefix: str = ""

    def to_dict(self) -> dict:
        """Serialise to a flat dict for SQLite storage."""
        d = asdict(self)
        d["failure_type"] = self.failure_type.value
        d["repair_attempted"] = int(self.repair_attempted)
        d["repair_successful"] = int(self.repair_successful)
        d["failed_output"] = (d.get("failed_output") or "")[:500]
        d["successful_output"] = (d.get("successful_output") or "")[:500]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CognitiveFailureRecord":
        """Deserialise from a flat dict returned by SQLite."""
        data = dict(d)
        data["failure_type"] = FailureType(data.get("failure_type", "unknown"))
        data["repair_attempted"] = bool(data.get("repair_attempted", 0))
        data["repair_successful"] = bool(data.get("repair_successful", 0))
        data.setdefault("recommended_spa_threshold", None)
        data.setdefault("recommended_n_drafts", None)
        data.setdefault("recommended_prompt_prefix", "")
        return cls(**data)

    def to_chroma_document(self) -> dict:
        """Format this record for ChromaDB upsert."""
        return {
            "id": self.record_id,
            "document": self.task_description,
            "metadata": {
                "node_type": self.node_type,
                "failure_type": self.failure_type.value,
                "repair_successful": str(self.repair_successful),
                "model_used": self.model_used,
                "created_at": self.created_at,
                "recommended_spa_threshold": str(
                    self.recommended_spa_threshold or ""
                ),
                "recommended_n_drafts": str(self.recommended_n_drafts or ""),
                "recommended_prompt_prefix": self.recommended_prompt_prefix,
            },
        }
