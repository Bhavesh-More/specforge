"""Failure detector — tracks consecutive failures and triggers the self-healing loop."""

from src.core.constants import SELF_HEALING_FAILURE_THRESHOLD
from src.core.logging import get_logger

_log = get_logger(__name__)


class FailureTracker:
    """Tracks consecutive failure counts per node and signals when healing is needed.

    Attributes:
        threshold: Number of consecutive failures before healing is triggered.
    """

    def __init__(
        self,
        threshold: int = SELF_HEALING_FAILURE_THRESHOLD,
    ) -> None:
        self._threshold = threshold
        self._failure_counts: dict[str, int] = {}
        self._failure_examples: dict[str, list[str]] = {}
        self._max_examples: int = 5

    def _key(self, template_id: str, node_id: str) -> str:
        return f"{template_id}:{node_id}"

    def record_failure(
        self,
        template_id: str,
        node_id: str,
        raw_output: str,
        error: str,
    ) -> bool:
        """Record a failed attempt for a node.

        Args:
            template_id: ID of the template being executed.
            node_id: ID of the node that failed.
            raw_output: The raw output string from the failed attempt.
            error: The error message string.

        Returns:
            True if the failure threshold has been reached and healing
            should be triggered; False otherwise.
        """
        k = self._key(template_id, node_id)
        self._failure_counts[k] = self._failure_counts.get(k, 0) + 1

        if k not in self._failure_examples:
            self._failure_examples[k] = []

        entry = f"[OUTPUT] {raw_output[:500]} [ERROR] {error}"
        self._failure_examples[k].append(entry)
        # Keep only last _max_examples
        self._failure_examples[k] = self._failure_examples[k][-self._max_examples:]

        _log.warning(
            "failure_recorded",
            template_id=template_id,
            node_id=node_id,
            count=self._failure_counts[k],
            threshold=self._threshold,
            should_heal=self._failure_counts[k] >= self._threshold,
        )

        return self._failure_counts[k] >= self._threshold

    def record_success(self, template_id: str, node_id: str) -> None:
        """Reset the failure count for a node after a successful attempt.

        Args:
            template_id: ID of the template.
            node_id: ID of the node.
        """
        k = self._key(template_id, node_id)
        self._failure_counts[k] = 0
        _log.info("success_recorded_clearing_failures", template_id=template_id, node_id=node_id)

    def get_failure_examples(self, template_id: str, node_id: str) -> list[str]:
        """Return stored failure examples for a node.

        Args:
            template_id: ID of the template.
            node_id: ID of the node.

        Returns:
            List of failure example strings.
        """
        return list(self._failure_examples.get(self._key(template_id, node_id), []))

    def should_heal(self, template_id: str, node_id: str) -> bool:
        """Return True if the failure count has reached the threshold.

        Args:
            template_id: ID of the template.
            node_id: ID of the node.

        Returns:
            True if healing should be triggered.
        """
        k = self._key(template_id, node_id)
        return self._failure_counts.get(k, 0) >= self._threshold

    def reset(self, template_id: str, node_id: str) -> None:
        """Clear failure count and examples for a node.

        Args:
            template_id: ID of the template.
            node_id: ID of the node.
        """
        k = self._key(template_id, node_id)
        self._failure_counts.pop(k, None)
        self._failure_examples.pop(k, None)
        _log.info("failure_tracker_reset", template_id=template_id, node_id=node_id)
