import uuid
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from enum import Enum


class FailureType(str, Enum):
    """
    Taxonomy of LLM node failures.
    Used for pattern detection and repair strategy routing.
    """
    SCHEMA_VIOLATION      = "schema_violation"
    # The output didn't match the expected JSON schema or output format.
    # Example: missing required field, wrong type, invalid nesting.

    HALLUCINATION_DRIFT   = "hallucination_drift"
    # The model drifted from the task and introduced unsupported facts.
    # Usually caught by high entropy (SPA) or factual validators.

    PREMATURE_CONCLUSION  = "premature_conclusion"
    # The model answered too quickly without sufficient reasoning.
    # Output too short, reasoning trace absent, assumptions unverified.

    LOGICAL_CONTRADICTION = "logical_contradiction"
    # The output contradicts itself or contradicts earlier nodes.

    CONTEXT_FORGETTING    = "context_forgetting"
    # The output ignores critical parts of the prompt or upstream context.

    OVER_GENERATION       = "over_generation"
    # Output too long, went off-topic, filled with irrelevant content.

    TOOL_MISUSE           = "tool_misuse"
    # Wrong output format for a downstream tool or symbolic node.

    UNKNOWN               = "unknown"
    # Unclassified failure — used as default until diagnosis is complete.


@dataclass
class CognitiveFailureRecord:
    """
    A complete record of one failed node execution.

    Design principle: store EVERYTHING that could be useful for future adaptation.
    Disk is cheap; missing signal is expensive.

    Two storage destinations:
    - SQLite: all structured fields → fast filtering by node_type, failure_type, date
    - ChromaDB: task_description field → semantic similarity search for "have we seen this?"
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Unique UUID for this record. Auto-generated.

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    # ISO 8601 UTC timestamp. Auto-generated.

    # ── Task context ──────────────────────────────────────────────────────────
    node_type: str = ""
    # The DAG node type. e.g. "extract_invoice", "reason_causal", "generate_plan".
    # Used for SQLite filtering and as a secondary signal in ChromaDB metadata.

    task_description: str = ""
    # The actual prompt or task text for this node.
    # THIS IS THE FIELD THAT GETS EMBEDDED in ChromaDB for semantic search.
    # When a new task arrives, we embed it and search against these descriptions.

    model_used: str = ""
    # Ollama model name. e.g. "llama3:8b", "qwen2:7b".
    # Different models may have different failure patterns.

    # ── Failure details ───────────────────────────────────────────────────────
    failure_type: FailureType = FailureType.UNKNOWN
    # Taxonomy classification. Used to route to the right repair strategy.

    validator_error: str = ""
    # The exact error message from the validator (JSON schema error, test failure, etc.)
    # Example: 'JSON parse error: required field "vendor_name" is missing'
    # This is what gets fed back to the model on repair — must be precise.

    failed_output: str = ""
    # What the model actually produced. Truncated to 500 chars for storage efficiency.

    entropy_at_failure: float = 0.0
    # Mean token entropy during the failed generation (from SPA monitor).
    # High entropy (>0.55) suggests hallucination drift was the root cause.

    # ── Repair details ────────────────────────────────────────────────────────
    repair_attempted: bool = False
    # Whether a repair was tried after the failure.

    repair_strategy_used: str = ""
    # What strategy was used for repair.
    # Examples: "strict_json_prompt", "budget_forcing", "adversarial_triad",
    #           "schema_first_prompt", "lower_temperature"

    repair_successful: bool = False
    # Whether the repair produced a valid output.

    successful_output: str = ""
    # The output that passed validation after repair. Truncated to 500 chars.
    # Used to update the CAS exemplar cache (Person 1's system).

    repair_prompt_delta: str = ""
    # What changed in the prompt that fixed it.
    # Example: "Added: 'Your JSON must include vendor_name field.'"

    # ── Adaptation hints ──────────────────────────────────────────────────────
    # These fields are filled AFTER a successful repair.
    # The MemoryAdapter reads them to configure future runs proactively.

    recommended_spa_threshold: Optional[float] = None
    # If set, lower SPA injection threshold by this amount for similar future tasks.
    # Example: 0.38 means "trigger pressure injection earlier than the default 0.50"

    recommended_n_drafts: Optional[int] = None
    # If set, increase SCS N drafts for similar future tasks.
    # Example: 7 means "this node type needs more trajectory sampling"

    recommended_prompt_prefix: str = ""
    # If set, prepend this text to the system prompt for similar future tasks.
    # Example: "Always include all required fields: vendor_name, line_items, total."

    def to_dict(self) -> dict:
        """
        Serialise to a flat dict for SQLite storage.
        """
        d = asdict(self)
        d["failure_type"] = self.failure_type.value   # Enum → string
        d["repair_attempted"] = int(self.repair_attempted)   # bool → int for SQLite
        d["repair_successful"] = int(self.repair_successful)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CognitiveFailureRecord":
        """
        Deserialise from a flat dict (as returned by SQLite fetchone).
        """
        d = d.copy()
        d["failure_type"] = FailureType(d.get("failure_type", "unknown"))
        d["repair_attempted"] = bool(d.get("repair_attempted", 0))
        d["repair_successful"] = bool(d.get("repair_successful", 0))
        # Handle None values for optional fields:
        d.setdefault("recommended_spa_threshold", None)
        d.setdefault("recommended_n_drafts", None)
        d.setdefault("recommended_prompt_prefix", "")
        return cls(**d)

    def to_chroma_document(self) -> dict:
        """
        Format for ChromaDB upsert.

        The 'document' field is what ChromaDB embeds and searches against.
        We use task_description because that's what we compare to when a new task arrives.

        Note: ChromaDB metadata values must be str, int, or float — no None allowed.
        Convert all None values to empty string "" before including in metadata.
        """
        return {
            "id": self.record_id,
            "document": self.task_description,
            "metadata": {
                "node_type": self.node_type,
                "failure_type": self.failure_type.value,
                "repair_successful": str(self.repair_successful),  # ChromaDB needs strings
                "model_used": self.model_used,
                "created_at": self.created_at,
                "recommended_spa_threshold": str(self.recommended_spa_threshold or ""),
                "recommended_n_drafts": str(self.recommended_n_drafts or ""),
                "recommended_prompt_prefix": self.recommended_prompt_prefix,
            }
        }
