"""Lookahead DAG — inference-time scaling via 3-path hypothesis generation."""

import asyncio
import json
from typing import Any

import httpx

from src.core.logging import get_logger
from src.models.cognitive_template import DAGNode, ExecutionTier
from src.models.execution import NodeResult, NodeStatus, ValidationResult
from src.executor.atomic_executor import AtomicExecutor
from src.executor.schema_validator import SchemaValidator

_log = get_logger(__name__)


# ─── HypothesisPath ────────────────────────────────────────────────────────────


class HypothesisPath:
    """A single hypothesis path generated during lookahead execution.

    Attributes:
        path_id: Single-letter identifier ('A', 'B', 'C').
        raw_output: Raw string output from Ollama.
        parsed_output: Parsed JSON dict if valid.
        validation_result: Outcome of JSON Schema validation.
        is_valid: True if the output passed validation.
        confidence_score: Heuristic score from 0.0 to 1.0.
    """

    def __init__(
        self,
        path_id: str,
        raw_output: str = "",
        parsed_output: dict[str, Any] | None = None,
        validation_result: ValidationResult | None = None,
        is_valid: bool = False,
        confidence_score: float = 0.0,
    ) -> None:
        self.path_id = path_id
        self.raw_output = raw_output
        self.parsed_output = parsed_output
        self.validation_result = validation_result
        self.is_valid = is_valid
        self.confidence_score = confidence_score


# ─── LookaheadDAG ───────────────────────────────────────────────────────────────


class LookaheadDAG:
    """Inference-time scaling via 3-path hypothesis generation and evaluation.

    Attributes:
        atomic_executor: AtomicExecutor for running Ollama calls.
        schema_validator: SchemaValidator for output validation.
        path_count: Number of parallel hypotheses to generate (default 3).
    """

    def __init__(
        self,
        atomic_executor: AtomicExecutor,
        schema_validator: SchemaValidator,
        path_count: int = 3,
    ) -> None:
        self._executor = atomic_executor
        self._validator = schema_validator
        self._path_count = path_count

    async def generate_hypotheses(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
    ) -> list[HypothesisPath]:
        """Run path_count parallel inference calls with slightly varied temperature.

        Args:
            node: The DAGNode to execute.
            global_state: Accumulated outputs from prior nodes.
            input_data: Top-level input payload.

        Returns:
            List of HypothesisPath objects.
        """
        path_ids = ["A", "B", "C", "D", "E", "F"][: self._path_count]

        # Vary temperature by ±0.05 per path for diversity
        base_temp = node.focus_prompt.temperature

        async def run_path(path_id: str, temp: float) -> HypothesisPath:
            # Build a patched node with modified temperature
            patched_node = node.model_copy(
                update={
                    "focus_prompt": node.focus_prompt.model_copy(
                        update={"temperature": temp}
                    )
                }
            )

            raw_output, rule_files = await self._executor.execute_node(
                node=patched_node,
                global_state=global_state,
                input_data=input_data,
                attempt_number=1,
                previous_error=None,
            )

            validation = self._validator.validate_output(
                raw_output, node.focus_prompt.output_schema
            )

            is_valid = validation.is_valid
            confidence = self.score_hypothesis_path(raw_output, is_valid, validation)

            return HypothesisPath(
                path_id=path_id,
                raw_output=raw_output,
                parsed_output=validation.parsed_output,
                validation_result=validation,
                is_valid=is_valid,
                confidence_score=confidence,
            )

        # Launch all paths concurrently
        temps = [
            base_temp + (i - self._path_count // 2) * 0.05
            for i in range(self._path_count)
        ]
        tasks = [run_path(pid, t) for pid, t in zip(path_ids, temps)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        hypotheses: list[HypothesisPath] = []
        first_exc: Exception | None = None
        for result in results:
            if isinstance(result, Exception):
                if first_exc is None:
                    first_exc = result
                _log.error("lookahead_path_error", error=str(result))
                continue
            hypotheses.append(result)

        # All paths failed — re-raise the original exception so the caller
        # sees the real error instead of an empty hypotheses list
        if len(hypotheses) == 0 and first_exc is not None:
            raise first_exc

        _log.info(
            "lookahead_hypotheses_generated",
            node_id=node.node_id,
            count=len(hypotheses),
        )
        return hypotheses

    def score_hypothesis_path(
        self,
        raw_output: str,
        is_valid: bool,
        validation: ValidationResult,
    ) -> float:
        """Heuristic confidence score for a hypothesis path.

        Args:
            raw_output: Raw string output.
            is_valid: Whether JSON parse succeeded.
            validation: The ValidationResult object.

        Returns:
            Score between 0.0 and 1.0.
        """
        score = 0.0

        if is_valid:
            score += 1.0
            if not validation.errors:
                score += 0.5

        if raw_output.strip():
            score += 0.2

        # Penalize hallucination/uncertainty markers
        LOWER_OUTPUT = raw_output.lower()
        if any(phrase in LOWER_OUTPUT for phrase in ("i cannot", "i don't know", "i'm not sure", "unable to", "cannot answer")):
            score -= 0.5

        return max(0.0, min(1.0, score))

    def score_hypothesis(self, path: HypothesisPath, schema: dict[str, Any]) -> float:
        """Score a HypothesisPath object.

        Args:
            path: The HypothesisPath to score.
            schema: The JSON schema (unused in current heuristic, reserved for future use).

        Returns:
            Confidence score from 0.0 to 1.0.
        """
        return self.score_hypothesis_path(
            path.raw_output, path.is_valid, path.validation_result
        )

    async def evaluate_and_select(
        self,
        hypotheses: list[HypothesisPath],
        node: DAGNode,
    ) -> HypothesisPath:
        """Score all hypotheses and select the best valid one.

        If multiple are equally valid, uses a lightweight evaluator prompt
        to pick the best.

        Args:
            hypotheses: List of HypothesisPath objects.
            node: The DAGNode (for schema context).

        Returns:
            The winning HypothesisPath.
        """
        for hyp in hypotheses:
            hyp.confidence_score = self.score_hypothesis(hyp, node.focus_prompt.output_schema)

        valid = [h for h in hypotheses if h.is_valid and h.confidence_score >= 0.5]

        if not valid:
            # No valid path — return highest scoring (even if invalid)
            best = max(hypotheses, key=lambda h: h.confidence_score)
            _log.warning(
                "no_valid_lookahead_path",
                node_id=node.node_id,
                best_score=best.confidence_score,
            )
            return best

        if len(valid) == 1:
            return valid[0]

        # Multiple valid — use evaluator LLM to pick best
        best = await self._llm_evaluate(valid, node)
        _log.info(
            "lookahead_evaluator_selected",
            node_id=node.node_id,
            selected_path=best.path_id,
            candidates=len(valid),
        )
        return best

    async def _llm_evaluate(
        self,
        candidates: list[HypothesisPath],
        node: DAGNode,
    ) -> HypothesisPath:
        """Lightweight LLM evaluator to pick best among valid candidates.

        Asks the model itself (via executor) to judge which output is best
        for the given task.

        Args:
            candidates: List of valid HypothesisPath objects.
            node: The DAGNode for task context.

        Returns:
            The selected HypothesisPath.
        """
        if len(candidates) == 1:
            return candidates[0]

        formatted = "\n\n".join(
            f"Path {c.path_id}:\n{c.raw_output[:300]}" for c in candidates
        )
        eval_prompt = (
            f"You are a judge. Pick the best output for the following task.\n\n"
            f"Task: {node.description}\n\n"
            f"Options:\n{formatted}\n\n"
            f"Respond with ONLY the path ID: A, B, C, etc."
        )

        judge_system = (
            "You are a strict evaluator. Choose the best candidate output. "
            "Respond with only a single path id such as A, B, or C."
        )
        judge_user = (
            f"Task: {node.description}\n\n"
            f"Candidates:\n{formatted}\n\n"
            "Return only the best path id."
        )

        judge_node = node.model_copy(
            update={
                "focus_prompt": node.focus_prompt.model_copy(
                    update={
                        "system_prompt": judge_system,
                        "user_template": judge_user,
                        "required_variables": [],
                    }
                )
            }
        )

        try:
            raw_output_eval, _ = await self._executor.execute_node(
                node=judge_node,
                global_state={},
                input_data={},
                attempt_number=1,
                previous_error=None,
            )

            chosen_id = raw_output_eval.strip().upper()[:1]
            for c in candidates:
                if c.path_id == chosen_id:
                    return c
        except Exception as exc:
            _log.warning("llm_evaluate_fallback", error=str(exc))

        # Fallback: highest confidence score
        return max(candidates, key=lambda h: h.confidence_score)

    async def execute_with_lookahead(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
    ) -> NodeResult:
        """Execute a node using lookahead hypothesis generation.

        Args:
            node: The DAGNode to execute.
            global_state: Accumulated outputs from prior nodes.
            input_data: Top-level input payload.

        Returns:
            A NodeResult with tier_used=ExecutionTier.DEEP and
            metadata about which path won.
        """
        hypotheses = await self.generate_hypotheses(node, global_state, input_data)
        winner = await self.evaluate_and_select(hypotheses, node)

        _log.info(
            "lookahead_execution_complete",
            node_id=node.node_id,
            winner_path=winner.path_id,
            winner_score=winner.confidence_score,
            total_paths=len(hypotheses),
        )

        return NodeResult(
            node_id=node.node_id,
            status=NodeStatus.PASSED_TIER3 if winner.is_valid else NodeStatus.FAILED,
            tier_used=ExecutionTier.DEEP,
            raw_output=winner.raw_output,
            parsed_output=winner.parsed_output,
            validation_result=winner.validation_result,
            attempt_count=self._path_count,
            execution_time_ms=0.0,  # Could aggregate from hypotheses
            rule_files_used=[],
            error_message=None if winner.is_valid else "All lookahead paths failed",
        )
