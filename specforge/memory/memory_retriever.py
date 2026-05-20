from dataclasses import dataclass, field
from typing import Optional
from collections import Counter

from .memory_store import MemoryStore
from .failure_record import CognitiveFailureRecord, FailureType


@dataclass
class RelevantMemories:
    """
    Packaged retrieval result for one incoming task.
    This is what MemoryAdapter reads to decide what to adapt.
    """

    similar_failures: list[tuple[CognitiveFailureRecord, float]]
    # List of (record, similarity_score) pairs, sorted by similarity descending.
    # Only includes records with similarity >= SIMILARITY_THRESHOLD.

    successful_repairs: list[CognitiveFailureRecord]
    # Subset of similar_failures where repair_successful == True.
    # These are the "what worked before" signals.

    dominant_failure_type: Optional[FailureType]
    # The most common FailureType among similar_failures.
    # None if there are too few failures to establish a pattern.

    historical_failure_rate: float
    # Fraction of past runs for this node_type that required repair.
    # 0.0 = always succeeds, 1.0 = always fails.

    has_relevant_memories: bool
    # True if at least one similar failure was found above the threshold.
    # If False, MemoryAdapter should not attempt adaptation.


class MemoryRetriever:
    """
    Packages raw MemoryStore data into actionable RelevantMemories.

    Called BEFORE each node execution to proactively check:
    "Have we failed on something like this before? What fixed it?"
    """

    SIMILARITY_THRESHOLD = 0.60
    # Minimum cosine similarity for a past failure to be considered "relevant".
    # Below this: the past failure was for a different enough task that it shouldn't
    # influence the current run. Tune this carefully — too low = false positives.

    MIN_FAILURES_FOR_PATTERN = 2
    # Need at least this many relevant failures to infer a dominant failure type.
    # Aligned with MemoryAdapter.MIN_MEMORIES_FOR_CONFIDENCE so that when we have
    # enough memories to adapt, we also have enough to detect the dominant pattern.

    def __init__(self, store: MemoryStore):
        self.store = store

    def retrieve_for_task(
        self,
        task_description: str,
        node_type: str,
        n_similar: int = 5,
    ) -> RelevantMemories:
        """
        Retrieve and package relevant memories for an incoming task.

        Args:
            task_description: the task text about to be executed
            node_type:        the node type (e.g. "extract_invoice")
            n_similar:        how many similar records to fetch from ChromaDB

        Returns:
            RelevantMemories
        """
        # STEP 1: Semantic search for similar past failures
        all_results = self.store.semantic_search(
            query_text=task_description,
            node_type_filter=node_type,
            n_results=n_similar,
        )
        # Filter to only those above threshold
        similar_failures = [
            (record, score)
            for record, score in all_results
            if score >= self.SIMILARITY_THRESHOLD
        ]

        # STEP 2: Extract successful repairs
        successful_repairs = [
            record
            for record, score in similar_failures
            if record.repair_successful
        ]

        # STEP 3: Compute dominant_failure_type
        if len(similar_failures) >= self.MIN_FAILURES_FOR_PATTERN:
            counts = Counter(record.failure_type for record, _ in similar_failures)
            dominant_failure_type = counts.most_common(1)[0][0]
        else:
            dominant_failure_type = None

        # STEP 4: Compute historical_failure_rate
        recent_records = self.store.get_by_node_type(node_type, limit=50)
        if len(recent_records) > 0:
            failed_count = sum(1 for r in recent_records if not r.repair_successful)
            historical_failure_rate = failed_count / len(recent_records)
        else:
            historical_failure_rate = 0.0

        # STEP 5: has_relevant_memories
        has_relevant_memories = len(similar_failures) > 0

        # STEP 6: Return RelevantMemories with all fields filled
        return RelevantMemories(
            similar_failures=similar_failures,
            successful_repairs=successful_repairs,
            dominant_failure_type=dominant_failure_type,
            historical_failure_rate=historical_failure_rate,
            has_relevant_memories=has_relevant_memories,
        )

    def get_best_repair_strategy(self, memories: RelevantMemories) -> Optional[str]:
        """
        Return the most commonly used repair strategy among successful repairs.
        Returns None if no successful repairs with a strategy exist.
        """
        if not memories.successful_repairs:
            return None
        strategy_counts = Counter(
            r.repair_strategy_used
            for r in memories.successful_repairs
            if r.repair_strategy_used
        )
        if not strategy_counts:
            return None
        return strategy_counts.most_common(1)[0][0]

    def get_recommended_prompt_additions(self, memories: RelevantMemories) -> list[str]:
        """
        Collect all non-empty recommended_prompt_prefix values from successful repairs,
        deduplicated, sorted by frequency (most recommended first).
        """
        prefixes = [
            r.recommended_prompt_prefix
            for r in memories.successful_repairs
            if r.recommended_prompt_prefix.strip()
        ]
        if not prefixes:
            return []
        counts = Counter(prefixes)
        # Deduplication is implicit — Counter aggregates duplicates
        return [prefix for prefix, count in counts.most_common()]
