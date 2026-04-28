"""Symbolic node executor — neuro-symbolic tool call execution for SYMBOLIC DAG nodes."""

import json
from typing import Any

from src.core.exceptions import MCPToolError, NodeExecutionError
from src.core.logging import get_logger
from src.models.execution import NodeResult, NodeStatus, ValidationResult
from src.models.cognitive_template import DAGNode, ExecutionTier, NodeType
from src.symbolic.mcp_client import MCPClient
from src.executor.atomic_executor import AtomicExecutor

_log = get_logger(__name__)


class SymbolicNodeExecutor:
    """Execute a SYMBOLIC-type DAG node via deterministic MCP tool calls.

    Two-phase execution:
    1. Translation: LLM expresses the problem as a JSON tool call intent
    2. Execution: Tool call is parsed and dispatched deterministically

    The computed result is GROUND TRUTH — it does not come from the LLM's
    probabilistic output.

    Attributes:
        mcp_client: MCPClient for tool execution.
        atomic_executor: AtomicExecutor for the translation LLM call.
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        atomic_executor: AtomicExecutor,
    ) -> None:
        self._mcp = mcp_client
        self._executor = atomic_executor

    async def execute(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
        model: str | None = None,
    ) -> NodeResult:
        """Execute a SYMBOLIC-type DAG node via MCP tool call.

        Args:
            node: The DAGNode to execute (must be NodeType.SYMBOLIC).
            global_state: Accumulated outputs from prior nodes.
            input_data: Top-level input payload.

        Returns:
            A NodeResult with the deterministic tool call result as parsed_output.

        Raises:
            NodeExecutionError: If translation or execution fails.
        """
        import time

        if node.node_type != NodeType.SYMBOLIC:
            raise NodeExecutionError(
                node_id=node.node_id,
                attempt_count=1,
                last_output="",
                context={"error": "SymbolicNodeExecutor requires NodeType.SYMBOLIC"},
            )

        tool_name = node.symbolic_tool
        if not tool_name:
            raise NodeExecutionError(
                node_id=node.node_id,
                attempt_count=1,
                last_output="",
                context={"error": "SYMBOLIC node has no symbolic_tool set"},
            )

        start_ms = time.perf_counter()

        # ── Phase 1: Translation — LLM proposes a tool call ───────────────

        tool = self._mcp._registry.get_tool(tool_name)
        tool_schema_str = json.dumps(tool.input_schema, indent=2) if tool else "{}"

        translation_system = (
            "You are a tool call generator. "
            "Express the user's problem as a JSON tool call. "
            "Output ONLY JSON — no explanation, no markdown."
        )

        translation_user = (
            f"Problem:\n{node.focus_prompt.user_template}\n\n"
            f"Available tool: {tool_name}\n"
            f"Tool input schema:\n{tool_schema_str}\n\n"
            f"Output ONLY JSON in this exact format:\n"
            f'{{"tool": "{tool_name}", "inputs": {{...}}}}'
        )

        translation_node = node.model_copy(
            update={
                "focus_prompt": node.focus_prompt.model_copy(
                    update={
                        "system_prompt": translation_system,
                        "user_template": translation_user,
                    }
                )
            }
        )

        raw_translation, _ = await self._executor.execute_node(
            node=translation_node,
            global_state=global_state,
            input_data=input_data,
            attempt_number=1,
            previous_error=None,
            model=model,
        )

        # ── Phase 2: Parse and execute the tool call ─────────────────────────

        try:
            parsed = json.loads(raw_translation)
            resolved_tool_name = parsed.get("tool", tool_name)
            tool_inputs = parsed.get("inputs", {})
        except json.JSONDecodeError as exc:
            raise NodeExecutionError(
                node_id=node.node_id,
                attempt_count=1,
                last_output=raw_translation,
                context={"error": f"Translation output not valid JSON: {exc.msg}"},
            )

        try:
            result = await self._mcp.call_tool(resolved_tool_name, tool_inputs)
        except MCPToolError as exc:
            raise NodeExecutionError(
                node_id=node.node_id,
                attempt_count=1,
                last_output=raw_translation,
                context={"error": f"Tool call failed: {exc.error_message}"},
            )

        elapsed_ms = (time.perf_counter() - start_ms) * 1000

        _log.info(
            "symbolic_node_executed",
            node_id=node.node_id,
            tool=resolved_tool_name,
            execution_time_ms=round(elapsed_ms, 2),
        )

        return NodeResult(
            node_id=node.node_id,
            status=NodeStatus.PASSED_TIER1,
            tier_used=ExecutionTier.FAST,
            raw_output=raw_translation,
            parsed_output=result,
            validation_result=ValidationResult(
                is_valid=True,
                errors=[],
                raw_output=raw_translation,
                parsed_output=result,
                validation_time_ms=0.0,
            ),
            attempt_count=1,
            execution_time_ms=elapsed_ms,
            rule_files_used=[],
            error_message=None,
        )
