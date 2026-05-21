"""Translate retrieved failures into proactive execution adaptations."""

from dataclasses import asdict, dataclass, field
from typing import Optional

from .failure_record import FailureType
from .memory_retriever import MemoryRetriever
from .memory_store import MemoryStore


@dataclass
class AdaptedExecutionConfig:
    """Modified config for an upcoming node execution."""

    n_drafts_override: Optional[int] = None
    scs_confidence_threshold: Optional[float] = None
    spa_inject_threshold_override: Optional[float] = None
    spa_warn_threshold_override: Optional[float] = None
    prompt_prefix_additions: list[str] = field(default_factory=list)
    force_deep_reason: bool = False
    adaptation_reason: str = ""
    confidence: float = 0.0
    memories_used: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class MemoryAdapter:
    """Turn relevant memories into concrete execution config changes."""

    MIN_MEMORIES_FOR_CONFIDENCE = 2
    HIGH_FAILURE_RATE_THRESHOLD = 0.40

    def __init__(self, retriever: MemoryRetriever):
        self.retriever = retriever

    def get_adapted_config(
        self,
        task_description: str,
        node_type: str,
        base_n_drafts: int = 5,
        base_inject_threshold: float = 0.50,
        base_warn_threshold: float = 0.30,
    ) -> AdaptedExecutionConfig:
        """Retrieve memories and return conservative proactive adaptations."""
        memories = self.retriever.retrieve_for_task(task_description, node_type)

        if not memories.has_relevant_memories:
            return AdaptedExecutionConfig(
                adaptation_reason="no relevant history found",
                memories_used=0,
            )

        n_mem = len(memories.similar_failures)
        if n_mem < self.MIN_MEMORIES_FOR_CONFIDENCE:
            return AdaptedExecutionConfig(
                adaptation_reason=(
                    f"insufficient history ({n_mem} memories, need "
                    f"{self.MIN_MEMORIES_FOR_CONFIDENCE})"
                ),
                memories_used=n_mem,
            )

        spa_inject = None
        spa_warn = None
        n_drafts = None
        scs_confidence = None
        force_deep = False
        prompt_additions: list[str] = []
        reasons: list[str] = []

        if memories.historical_failure_rate > self.HIGH_FAILURE_RATE_THRESHOLD:
            spa_inject = max(0.28, base_inject_threshold - 0.12)
            spa_warn = max(0.18, base_warn_threshold - 0.08)
            scs_confidence = 0.78
            reasons.append(
                f"tightened controls (failure rate: {memories.historical_failure_rate:.0%})"
            )

        dominant = memories.dominant_failure_type
        if dominant == FailureType.SCHEMA_VIOLATION:
            prompt_additions.append(
                "CRITICAL: Your output MUST exactly match the required format/schema. "
                "Verify every required field is present and correctly typed before responding."
            )
            reasons.append("added schema enforcement prefix (past schema violations)")

        if dominant == FailureType.HALLUCINATION_DRIFT:
            n_drafts = min(base_n_drafts + 2, 9)
            spa_inject = min(
                spa_inject or base_inject_threshold,
                max(0.32, base_inject_threshold - 0.10),
            )
            reasons.append(f"increased SCS to N={n_drafts} (past hallucination drift)")

        if dominant == FailureType.PREMATURE_CONCLUSION:
            force_deep = True
            prompt_additions.append(
                "Think through this problem step by step before giving your answer. "
                "Do not state a conclusion until you have fully reasoned through all aspects."
            )
            reasons.append("forced deep reasoning (past premature conclusions)")

        if dominant == FailureType.LOGICAL_CONTRADICTION:
            prompt_additions.append(
                "Before finalising your answer, check it for internal consistency. "
                "Ensure no statement contradicts another in your response."
            )
            reasons.append("added consistency check prefix (past contradictions)")

        if dominant == FailureType.OVER_GENERATION:
            prompt_additions.append(
                "Be concise. Answer only what was asked. Stop when the task is complete."
            )
            reasons.append("added conciseness prefix (past over-generation)")

        new_prefixes = self.retriever.get_recommended_prompt_additions(memories)
        for prefix in new_prefixes:
            if prefix not in prompt_additions:
                prompt_additions.append(prefix)
        if new_prefixes:
            reasons.append(
                f"added {len(new_prefixes)} prefix(es) from successful past repairs"
            )

        recommended_spa = [
            record.recommended_spa_threshold
            for record in memories.successful_repairs
            if record.recommended_spa_threshold is not None
        ]
        if recommended_spa:
            spa_inject = min(spa_inject or base_inject_threshold, min(recommended_spa))
            reasons.append(f"used stored SPA recommendation ({spa_inject:.2f})")

        recommended_n = [
            record.recommended_n_drafts
            for record in memories.successful_repairs
            if record.recommended_n_drafts is not None
        ]
        if recommended_n:
            n_drafts = max(n_drafts or base_n_drafts, max(recommended_n))
            reasons.append(f"used stored SCS recommendation (N={n_drafts})")

        confidence = min(1.0, n_mem / 10.0)
        return AdaptedExecutionConfig(
            n_drafts_override=n_drafts,
            scs_confidence_threshold=scs_confidence,
            spa_inject_threshold_override=spa_inject,
            spa_warn_threshold_override=spa_warn,
            prompt_prefix_additions=prompt_additions,
            force_deep_reason=force_deep,
            adaptation_reason="; ".join(reasons) if reasons else "no adaptations needed",
            confidence=confidence,
            memories_used=n_mem,
        )

    def record_execution_outcome(
        self,
        store: MemoryStore,
        record_id: str,
        repair_successful: bool,
        successful_output: str = "",
        repair_prompt_delta: str = "",
        recommended_spa_threshold: Optional[float] = None,
        recommended_n_drafts: Optional[int] = None,
        recommended_prompt_prefix: str = "",
    ) -> None:
        """Update a record after repair completes."""
        store.update_repair_outcome(
            record_id=record_id,
            repair_successful=repair_successful,
            successful_output=successful_output[:500],
            repair_prompt_delta=repair_prompt_delta,
            recommended_spa_threshold=recommended_spa_threshold,
            recommended_n_drafts=recommended_n_drafts,
            recommended_prompt_prefix=recommended_prompt_prefix,
        )
