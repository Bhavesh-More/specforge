"""Cognitive rollback — prune failed reasoning paths before error propagation."""

from typing import Any

from src.core.logging import get_logger
from src.reasoning.lookahead_dag import HypothesisPath

_log = get_logger(__name__)

HALLUCINATION_MARKERS = (
    "i cannot",
    "i don't know",
    "i'm not sure",
    "unable to",
    "cannot answer",
    "i'm unable",
    "not possible",
    "i cannot answer",
    "i don't have enough information",
)


class CognitiveRollback:
    """Prunes failed reasoning paths before errors propagate to downstream nodes.

    The rollback logic determines which paths are unrecoverable and should be
    discarded versus which might still be valid with correction.
    """

    def should_rollback(self, path: HypothesisPath) -> bool:
        """Determine if a hypothesis path should be rolled back.

        A path should be rolled back if it is:
        - Not valid JSON
        - Has more than 2 schema validation errors
        - Contains obvious hallucination markers

        Args:
            path: The HypothesisPath to evaluate.

        Returns:
            True if the path should be pruned/rolled back.
        """
        # Not valid JSON at all
        if not path.is_valid:
            _log.info("rollback_json_invalid", path_id=path.path_id)
            return True

        # Too many schema errors
        if path.validation_result and len(path.validation_result.errors) > 2:
            _log.info(
                "rollback_schema_errors",
                path_id=path.path_id,
                error_count=len(path.validation_result.errors),
            )
            return True

        # Hallucination markers
        lower = path.raw_output.lower()
        if any(marker in lower for marker in HALLUCINATION_MARKERS):
            _log.info("rollback_hallucination_marker", path_id=path.path_id)
            return True

        return False

    def select_best_valid_path(
        self, paths: list[HypothesisPath]
    ) -> HypothesisPath | None:
        """Filter to valid paths, return highest-confidence.

        Args:
            paths: List of HypothesisPath objects.

        Returns:
            The best valid HypothesisPath, or None if all failed.
        """
        valid = [
            p for p in paths
            if p.is_valid and p.validation_result and not p.validation_result.errors
        ]

        if not valid:
            # Fall back to any valid path
            valid = [p for p in paths if p.is_valid]

        if not valid:
            _log.warning("all_lookahead_paths_failed")
            return None

        best = max(valid, key=lambda p: p.confidence_score)
        _log.info(
            "best_valid_path_selected",
            path_id=best.path_id,
            confidence=best.confidence_score,
            valid_count=len(valid),
        )
        return best

    def apply_rollback(self, paths: list[HypothesisPath]) -> list[HypothesisPath]:
        """Remove paths that should be rolled back.

        Args:
            paths: List of HypothesisPath objects to evaluate.

        Returns:
            Filtered list of HypothesisPath objects with failed paths removed.
        """
        original_count = len(paths)
        remaining: list[HypothesisPath] = []

        for path in paths:
            if self.should_rollback(path):
                _log.info(
                    "path_rolled_back",
                    path_id=path.path_id,
                    reason=self._rollback_reason(path),
                )
            else:
                remaining.append(path)

        _log.info(
            "rollback_complete",
            original=original_count,
            remaining=len(remaining),
            rolled_back=original_count - len(remaining),
        )
        return remaining

    # ─── Internals ─────────────────────────────────────────────────────────────

    def _rollback_reason(self, path: HypothesisPath) -> str:
        """Return a human-readable reason for why a path was rolled back."""
        if not path.is_valid:
            return "invalid_json"
        if path.validation_result and len(path.validation_result.errors) > 2:
            return f"schema_errors:{len(path.validation_result.errors)}"
        lower = path.raw_output.lower()
        for marker in HALLUCINATION_MARKERS:
            if marker in lower:
                return f"hallucination_marker:{marker}"
        return "unknown"
