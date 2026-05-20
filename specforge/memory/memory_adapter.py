from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from .memory_retriever import MemoryRetriever, RelevantMemories
from .failure_record import CognitiveFailureRecord, FailureType

if TYPE_CHECKING:
    from .memory_store import MemoryStore


@dataclass
class AdaptedExecutionConfig:
    """
    The output of MemoryAdapter — a modified config for the upcoming node execution.

    All fields are Optional with None meaning "use the default from the node config".
    The caller only overrides what is explicitly set here.
    """

    # SCS (Speculative Consistency Sampling) adaptations
    n_drafts_override: Optional[int] = None
    # If set, use this N for SCS instead of the node's default.
    # Increased when we've seen false clusters or high failure rates.

    scs_confidence_threshold: Optional[float] = None
    # If set, require this confidence score from SCS before proceeding.
    # Increased for high-failure nodes (more conservative escalation).

    # SPA (Semantic Pressure Annealing) adaptations
    spa_inject_threshold_override: Optional[float] = None
    # If set, use this as the entropy injection threshold.
    # Lower value = tighter control = pressure injected sooner.

    spa_warn_threshold_override: Optional[float] = None
    # If set, use this as the entropy warn threshold.

    # Prompt adaptations
    prompt_prefix_additions: list[str] = field(default_factory=list)
    # Strings to prepend to the system prompt before execution.
    # Accumulated from successful repair strategies in past similar runs.

    # Reasoning adaptations
    force_deep_reason: bool = False
    # If True, override node_type to "deep_reason" regardless of original type.
    # Used when premature_conclusion failures are dominant.

    # Meta fields (for logging and explainability)
    adaptation_reason: str = ""
    # Human-readable explanation of what was adapted and why.
    # Example: "Lowered SPA threshold to 0.38 due to 67% hallucination_drift rate"

    confidence: float = 0.0
    # How confident we are in this adaptation (0.0 = no evidence, 1.0 = strong evidence).
    # Scales with number of relevant memories used.

    memories_used: int = 0
    # How many relevant memory records informed this adaptation.


class MemoryAdapter:
    """
    Translates retrieved memories into concrete execution config changes.

    Calling get_adapted_config() before a node runs is the entire FMB feedback loop:
    1. Retrieve memories relevant to this task
    2. Identify patterns (dominant failure type, historical failure rate)
    3. Apply evidence-based adaptations
    4. Return AdaptedExecutionConfig for the caller to apply

    Philosophy: be CONSERVATIVE. Only adapt when there is strong evidence.
    False positives (unnecessary restriction) hurt creative/brainstorming nodes.
    False negatives (missing a needed restriction) are caught by the retry loop anyway.
    """

    MIN_MEMORIES_FOR_CONFIDENCE = 2
    # Minimum relevant memories needed before we make any adaptation.
    # With 0 or 1 relevant memory, we could be overfitting to a coincidence.

    HIGH_FAILURE_RATE_THRESHOLD = 0.40
    # If historical_failure_rate > this, the node is "high-risk" → tighten controls.

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
        """
        Main entry point. Retrieve memories and return an adapted config.

        Args:
            task_description:       the task text about to be executed
            node_type:              e.g. "extract_invoice"
            base_n_drafts:          the node's default SCS N
            base_inject_threshold:  the node's default SPA injection threshold
            base_warn_threshold:    the node's default SPA warn threshold

        Returns:
            AdaptedExecutionConfig
        """
        # STEP 1: Retrieve memories
        memories = self.retriever.retrieve_for_task(task_description, node_type)

        # STEP 2: Early exit if no memories
        if not memories.has_relevant_memories:
            return AdaptedExecutionConfig(
                adaptation_reason="no relevant history found",
                memories_used=0,
            )

        # STEP 3: Early exit if too few memories for confidence
        n_mem = len(memories.similar_failures)
        if n_mem < self.MIN_MEMORIES_FOR_CONFIDENCE:
            return AdaptedExecutionConfig(
                adaptation_reason=f"insufficient history ({n_mem} memories, need {self.MIN_MEMORIES_FOR_CONFIDENCE})",
                memories_used=n_mem,
            )

        # STEP 4: Build the adapted config by applying adaptation rules
        spa_inject: Optional[float] = None
        spa_warn: Optional[float] = None
        n_drafts: Optional[int] = None
        force_deep = False
        prompt_additions: list[str] = []
        reasons: list[str] = []

        # RULE A — HIGH FAILURE RATE → tighten SPA thresholds
        if memories.historical_failure_rate > self.HIGH_FAILURE_RATE_THRESHOLD:
            spa_inject = max(0.28, base_inject_threshold - 0.12)
            spa_warn   = max(0.18, base_warn_threshold   - 0.08)
            reasons.append(
                f"tightened SPA thresholds (failure rate: "
                f"{memories.historical_failure_rate:.0%})"
            )

        # RULE B — SCHEMA_VIOLATION dominant → add format reminder
        if memories.dominant_failure_type == FailureType.SCHEMA_VIOLATION:
            prompt_additions.append(
                "CRITICAL: Your output MUST exactly match the required format/schema. "
                "Verify every required field is present and correctly typed before responding."
            )
            reasons.append("added schema enforcement prefix (past schema violations)")

        # RULE C — HALLUCINATION_DRIFT dominant → more SCS + tighter SPA
        if memories.dominant_failure_type == FailureType.HALLUCINATION_DRIFT:
            n_drafts = min(base_n_drafts + 2, 9)
            spa_inject = min(
                spa_inject or base_inject_threshold,
                max(0.32, base_inject_threshold - 0.10)
            )
            reasons.append(
                f"increased SCS to N={n_drafts} (past hallucination drift)"
            )

        # RULE D — PREMATURE_CONCLUSION dominant → force deep reasoning
        if memories.dominant_failure_type == FailureType.PREMATURE_CONCLUSION:
            force_deep = True
            prompt_additions.append(
                "Think through this problem step by step before giving your answer. "
                "Do not state a conclusion until you have fully reasoned through all aspects."
            )
            reasons.append("forced deep reasoning (past premature conclusions)")

        # RULE E — LOGICAL_CONTRADICTION dominant → add self-check reminder
        if memories.dominant_failure_type == FailureType.LOGICAL_CONTRADICTION:
            prompt_additions.append(
                "Before finalising your answer, check it for internal consistency. "
                "Ensure no statement contradicts another in your response."
            )
            reasons.append("added consistency check prefix (past contradictions)")

        # RULE F — OVER_GENERATION dominant → add length constraint
        if memories.dominant_failure_type == FailureType.OVER_GENERATION:
            prompt_additions.append(
                "Be concise. Answer only what was asked. Stop when the task is complete."
            )
            reasons.append("added conciseness prefix (past over-generation)")

        # RULE G — Add successful repair prompt prefixes
        new_prefixes = self.retriever.get_recommended_prompt_additions(memories)
        for prefix in new_prefixes:
            if prefix not in prompt_additions:
                prompt_additions.append(prefix)
        if new_prefixes:
            reasons.append(
                f"added {len(new_prefixes)} prefix(es) from successful past repairs"
            )

        # STEP 5: Compute confidence
        confidence = min(1.0, n_mem / 10.0)
        # Scales linearly: 0 memories → 0.0, 10+ memories → 1.0

        # STEP 6: Build and return AdaptedExecutionConfig
        return AdaptedExecutionConfig(
            n_drafts_override=n_drafts,
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
        store: "MemoryStore",
        record_id: str,
        repair_successful: bool,
        successful_output: str = "",
        repair_prompt_delta: str = "",
        recommended_spa_threshold: Optional[float] = None,
        recommended_n_drafts: Optional[int] = None,
        recommended_prompt_prefix: str = "",
    ) -> None:
        """
        After a node execution completes (success or failure), update the record.
        This closes the feedback loop — the memory learns from this run.

        Called by the DAG executor after each node finishes.
        """
        store.update_repair_outcome(
            record_id=record_id,
            repair_successful=repair_successful,
            successful_output=successful_output[:500],  # truncate for storage
            repair_prompt_delta=repair_prompt_delta,
            recommended_spa_threshold=recommended_spa_threshold,
            recommended_n_drafts=recommended_n_drafts,
            recommended_prompt_prefix=recommended_prompt_prefix,
        )
