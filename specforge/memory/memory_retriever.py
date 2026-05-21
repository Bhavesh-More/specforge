"""High-level retrieval interface for Failure Memory Bank."""

from collections import Counter
from dataclasses import dataclass
from typing import Optional

from .failure_record import CognitiveFailureRecord, FailureType
from .memory_store import MemoryStore


@dataclass
class RelevantMemories:
    """Packaged retrieval result for one incoming task."""

    similar_failures: list[tuple[CognitiveFailureRecord, float]]
    successful_repairs: list[CognitiveFailureRecord]
    dominant_failure_type: Optional[FailureType]
    historical_failure_rate: float
    has_relevant_memories: bool


class MemoryRetriever:
    """Packages raw memory records into actionable retrieval results."""

    SIMILARITY_THRESHOLD = 0.60
    MIN_FAILURES_FOR_PATTERN = 3

    def __init__(self, store: MemoryStore):
        self.store = store

    def retrieve_for_task(
        self,
        task_description: str,
        node_type: str,
        n_similar: int = 5,
    ) -> RelevantMemories:
        """Retrieve and package relevant memories for an incoming task."""
        all_results = self.store.semantic_search(
            query_text=task_description,
            node_type_filter=node_type,
            n_results=n_similar,
        )
        similar_failures = [
            (record, score)
            for record, score in all_results
            if score >= self.SIMILARITY_THRESHOLD
        ]
        successful_repairs = [
            record for record, _score in similar_failures if record.repair_successful
        ]

        if len(similar_failures) >= self.MIN_FAILURES_FOR_PATTERN:
            counts = Counter(record.failure_type for record, _ in similar_failures)
            dominant_failure_type = counts.most_common(1)[0][0]
        else:
            dominant_failure_type = None

        recent_records = self.store.get_by_node_type(node_type, limit=50)
        if recent_records:
            failed_count = sum(1 for record in recent_records if not record.repair_successful)
            historical_failure_rate = failed_count / len(recent_records)
        else:
            historical_failure_rate = 0.0

        return RelevantMemories(
            similar_failures=similar_failures,
            successful_repairs=successful_repairs,
            dominant_failure_type=dominant_failure_type,
            historical_failure_rate=historical_failure_rate,
            has_relevant_memories=bool(similar_failures),
        )

    def get_best_repair_strategy(self, memories: RelevantMemories) -> Optional[str]:
        """Return the most common repair strategy among successful repairs."""
        if not memories.successful_repairs:
            return None
        strategy_counts = Counter(
            record.repair_strategy_used
            for record in memories.successful_repairs
            if record.repair_strategy_used
        )
        if not strategy_counts:
            return None
        return strategy_counts.most_common(1)[0][0]

    def get_recommended_prompt_additions(
        self,
        memories: RelevantMemories,
    ) -> list[str]:
        """Return deduplicated prompt prefixes from successful repairs."""
        prefixes = [
            record.recommended_prompt_prefix
            for record in memories.successful_repairs
            if record.recommended_prompt_prefix.strip()
        ]
        if not prefixes:
            return []
        counts = Counter(prefixes)
        return [prefix for prefix, _count in counts.most_common()]
