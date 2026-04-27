"""Confidence gate — three-tier orchestration engine and top-level SpecForge execution engine."""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.logging import get_logger
from src.core.exceptions import NodeExecutionError
from src.executor.result_weaver import ResultWeaver, StateFileWriter
from src.compiler.template_registry import TemplateRegistry
from src.knowledge.graph_manager import KnowledgeGraphManager
from src.models.cognitive_template import CognitiveTemplate, DAGNode, ExecutionTier, NodeType
from src.models.execution import ExecutionRun, ExecutionStatus, NodeResult, NodeStatus
from src.reasoning.adversarial_triad import AdversarialTriad
from src.reasoning.lookahead_dag import LookaheadDAG
from src.reasoning.cognitive_rollback import CognitiveRollback
from src.symbolic.symbolic_node import SymbolicNodeExecutor

_log = get_logger(__name__)


# ─── ConfidenceGate ───────────────────────────────────────────────────────────


class ConfidenceGate:
    """Three-tier execution orchestrator for a single DAG node.

    Decides which execution tier to use based on node type and prior results.
    Escalates to adversarial/lookahead only when Fast + Repair paths fail.

    Attributes:
        retry_orchestrator: Handles Fast + Repair tier execution.
        adversarial_triad: Handles DEEP tier for standard nodes.
        lookahead_dag: Handles DEEP tier for LOOKAHEAD nodes.
        symbolic_executor: Handles SYMBOLIC nodes (always deterministic).
        failure_tracker: Tracks consecutive failures per node.
        healing_orchestrator: Triggers self-healing on repeated failures.
    """

    def __init__(
        self,
        retry_orchestrator: "RetryOrchestrator",
        adversarial_triad: AdversarialTriad,
        lookahead_dag: LookaheadDAG,
        symbolic_executor: SymbolicNodeExecutor,
        failure_tracker: "FailureTracker",
        healing_orchestrator: "SelfHealingOrchestrator",
    ) -> None:
        self._retry = retry_orchestrator
        self._triad = adversarial_triad
        self._lookahead = lookahead_dag
        self._symbolic = symbolic_executor
        self._tracker = failure_tracker
        self._healing = healing_orchestrator

    async def execute_node(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
        template_id: str,
        run_id: str,
    ) -> NodeResult:
        """Execute a single node through the appropriate tier.

        Args:
            node: The DAGNode to execute.
            global_state: Accumulated outputs from prior executed nodes.
            input_data: Top-level input payload.
            template_id: ID of the template being executed.
            run_id: ID of the current execution run.

        Returns:
            A NodeResult with the execution result.
        """
        _log.info(
            "confidence_gate_start",
            node_id=node.node_id,
            node_type=node.node_type.value,
            template_id=template_id,
        )

        # ── STEP 1: Pre-route based on NodeType ─────────────────────────────

        if node.node_type == NodeType.SYMBOLIC:
            result = await self._symbolic.execute(node, global_state, input_data)
            self._tracker.record_success(template_id, node.node_id)
            return result

        if node.node_type == NodeType.ADVERSARIAL:
            result = await self._triad.execute_triad(node, global_state, input_data)
            if result.status in {NodeStatus.PASSED_TIER1, NodeStatus.PASSED_TIER2, NodeStatus.PASSED_TIER3}:
                self._tracker.record_success(template_id, node.node_id)
                _log.info(
                    "confidence_gate_triad_passed",
                    node_id=node.node_id,
                    tier=result.tier_used.value,
                )
            else:
                _log.warning(
                    "confidence_gate_triad_failed_falling_back_to_retry",
                    node_id=node.node_id,
                    template_id=template_id,
                )
                fallback = await self._retry.execute_with_retry(node, global_state, input_data)
                if fallback.status in {NodeStatus.PASSED_TIER1, NodeStatus.PASSED_TIER2, NodeStatus.PASSED_TIER3}:
                    self._tracker.record_success(template_id, node.node_id)
                    return fallback
                await self._record_failure_and_trigger_healing(
                    template_id, node, fallback, run_id,
                )
                return fallback
            return result

        if node.node_type == NodeType.LOOKAHEAD:
            result = await self._lookahead.execute_with_lookahead(node, global_state, input_data)
            if result.status in {NodeStatus.PASSED_TIER1, NodeStatus.PASSED_TIER2, NodeStatus.PASSED_TIER3}:
                self._tracker.record_success(template_id, node.node_id)
                _log.info(
                    "confidence_gate_lookahead_passed",
                    node_id=node.node_id,
                    tier=result.tier_used.value,
                )
            else:
                _log.warning(
                    "confidence_gate_lookahead_failed_falling_back_to_retry",
                    node_id=node.node_id,
                    template_id=template_id,
                )
                fallback = await self._retry.execute_with_retry(node, global_state, input_data)
                if fallback.status in {NodeStatus.PASSED_TIER1, NodeStatus.PASSED_TIER2, NodeStatus.PASSED_TIER3}:
                    self._tracker.record_success(template_id, node.node_id)
                    return fallback
                await self._record_failure_and_trigger_healing(
                    template_id, node, fallback, run_id,
                )
                return fallback
            return result

        # ── STEP 2: Fast + Repair tiers (STANDARD / PARALLEL) ─────────────

        result = await self._retry.execute_with_retry(node, global_state, input_data)

        if result.status in {NodeStatus.PASSED_TIER1, NodeStatus.PASSED_TIER2}:
            self._tracker.record_success(template_id, node.node_id)
            _log.info(
                "confidence_gate_tier1_or_tier2_passed",
                node_id=node.node_id,
                tier=result.tier_used.value,
            )
            return result

        # ── STEP 3: Deep Path (only if Tier 1 + 2 both failed) ──────────────

        if node.node_type == NodeType.LOOKAHEAD:
            deep_result = await self._lookahead.execute_with_lookahead(node, global_state, input_data)
        else:
            deep_result = await self._triad.execute_triad(node, global_state, input_data)

        if deep_result.status in {NodeStatus.PASSED_TIER1, NodeStatus.PASSED_TIER2, NodeStatus.PASSED_TIER3}:
            self._tracker.record_success(template_id, node.node_id)
            _log.info(
                "confidence_gate_deep_path_passed",
                node_id=node.node_id,
                tier=deep_result.tier_used.value,
            )
            return deep_result

        # ── STEP 4: All tiers failed — record + trigger healing ───────────

        await self._record_failure_and_trigger_healing(
            template_id, node, deep_result, run_id,
        )
        return deep_result

    async def _record_failure_and_trigger_healing(
        self,
        template_id: str,
        node: DAGNode,
        result: NodeResult,
        run_id: str,
    ) -> None:
        """Record failure and non-blocking trigger the healing orchestrator."""
        self._tracker.record_failure(
            template_id=template_id,
            node_id=node.node_id,
            raw_output=result.raw_output,
            error=result.error_message or "",
        )

        # Non-blocking healing trigger
        asyncio.create_task(
            self._healing.process_node_failure(
                template_id=template_id,
                node=node,
                raw_output=result.raw_output,
                error=result.error_message or "",
                run_id=run_id,
            )
        )

        _log.warning(
            "confidence_gate_all_tiers_failed",
            node_id=node.node_id,
            template_id=template_id,
            run_id=run_id,
            healing_triggered=True,
        )


# ─── SpecForgeEngine ───────────────────────────────────────────────────────────


class SpecForgeEngine:
    """Top-level execution engine for an entire CognitiveTemplate.

    Coordinates wave-based parallel execution, state file maintenance,
    human-in-the-loop edits, and final output assembly.

    Attributes:
        confidence_gate: ConfidenceGate for per-node execution.
        result_weaver: ResultWeaver for final output assembly.
        state_writer: StateFileWriter for state.md maintenance.
        template_registry: TemplateRegistry for template loading.
        knowledge_manager: KnowledgeGraphManager for context assembly.
    """

    def __init__(
        self,
        confidence_gate: ConfidenceGate,
        result_weaver: ResultWeaver,
        state_writer: StateFileWriter,
        template_registry: TemplateRegistry,
        knowledge_manager: KnowledgeGraphManager,
    ) -> None:
        self._gate = confidence_gate
        self._weaver = result_weaver
        self._state = state_writer
        self._registry = template_registry
        self._kg = knowledge_manager

    async def execute_template(
        self,
        template: CognitiveTemplate,
        input_data: dict[str, Any],
        output_dir: Path,
        run_id: str | None = None,
    ) -> ExecutionRun:
        """Execute an entire CognitiveTemplate end-to-end.

        Args:
            template: The CognitiveTemplate to execute.
            input_data: Top-level input payload.
            output_dir: Directory for state.md and other outputs.
            run_id: Optional run ID; generated if not provided.

        Returns:
            A completed ExecutionRun with all node results and final output.
        """
        import time

        rid = run_id or str(uuid.uuid4())
        start_ms = time.perf_counter()

        execution_run = ExecutionRun(
            run_id=rid,
            template_id=template.template_id,
            template_name=template.name,
            status=ExecutionStatus.RUNNING,
            input_data=input_data,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        state_path = output_dir / "state.md"
        self._state._path = state_path  # inject path into shared state writer
        execution_run.state_file_path = str(state_path)

        await self._state.initialize(execution_run, template)
        await self._kg.initialize()

        global_state: dict[str, Any] = {}
        critical_path = set(template.get_execution_order()[0] if template.get_execution_order() else [])

        waves = template.get_execution_order()

        _log.info(
            "execution_start",
            run_id=rid,
            template_id=template.template_id,
            total_waves=len(waves),
        )

        for wave_idx, wave in enumerate(waves):
            _log.info("wave_start", run_id=rid, wave=wave_idx, nodes=wave)

            wave_tasks = [
                self._gate.execute_node(
                    node=self._find_node(template, node_id),
                    global_state=global_state,
                    input_data=input_data,
                    template_id=template.template_id,
                    run_id=rid,
                )
                for node_id in wave
            ]

            wave_results = await asyncio.gather(*wave_tasks, return_exceptions=True)

            for node_id, result in zip(wave, wave_results):
                node = self._find_node(template, node_id)

                if isinstance(result, Exception):
                    error_message = str(result)
                    attempt_count = 0
                    if isinstance(result, NodeExecutionError):
                        attempt_count = result.attempt_count
                        missing_var = result.context.get("missing_variable")
                        missing_tpl_var = result.context.get("missing_template_variable")
                        if missing_var:
                            error_message = (
                                f"{error_message}. Missing required input variable: '{missing_var}'"
                            )
                        elif missing_tpl_var:
                            error_message = (
                                f"{error_message}. Missing template variable: '{missing_tpl_var}'"
                            )

                    result = NodeResult(
                        node_id=node_id,
                        status=NodeStatus.FAILED,
                        tier_used=ExecutionTier.FAST,
                        raw_output="",
                        attempt_count=attempt_count,
                        error_message=error_message,
                    )

                # Check for human edits before propagating output
                if result.parsed_output:
                    result.parsed_output = await self._weaver.check_for_human_edits(
                        node_id, result.parsed_output,
                    )

                execution_run.node_results[node_id] = result
                global_state = self._weaver.update_global_state(global_state, node, result)
                await self._state.append_node_result(node, result)

                # Abort on critical path failure
                if node_id in critical_path and result.status == NodeStatus.FAILED:
                    _log.error(
                        "critical_path_node_failed_aborting",
                        run_id=rid,
                        node_id=node_id,
                    )
                    execution_run.status = ExecutionStatus.FAILED
                    node_error = result.error_message
                    execution_run.error_message = (
                        f"Critical path node '{node_id}' failed: {node_error}"
                        if node_error
                        else f"Critical path node '{node_id}' failed"
                    )
                    execution_run.completed_at = datetime.now(timezone.utc)
                    execution_run.total_execution_time_ms = (time.perf_counter() - start_ms) * 1000
                    await self._state.finalize(execution_run, success=False)
                    return execution_run

        # All waves complete
        any_failed = any(
            result.status == NodeStatus.FAILED
            for result in execution_run.node_results.values()
        )
        execution_run.status = ExecutionStatus.FAILED if any_failed else ExecutionStatus.COMPLETED
        execution_run.completed_at = datetime.now(timezone.utc)
        execution_run.total_execution_time_ms = (time.perf_counter() - start_ms) * 1000
        execution_run.final_output = self._weaver.assemble_final_output(
            global_state, template, execution_run,
        )

        await self._state.finalize(execution_run, success=not any_failed)

        _log.info(
            "execution_complete",
            run_id=rid,
            total_time_ms=round(execution_run.total_execution_time_ms or 0, 2),
            nodes_executed=len(execution_run.node_results),
        )

        return execution_run

    def _find_node(self, template: CognitiveTemplate, node_id: str) -> DAGNode:
        """Find a DAGNode by node_id within a template."""
        for node in template.nodes:
            if node.node_id == node_id:
                return node
        raise ValueError(f"Node '{node_id}' not found in template")
