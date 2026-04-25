"""Adversarial Triad — Creator → Cynic → Resolver reasoning pattern."""

import json
from typing import Any

from src.core.logging import get_logger
from src.models.cognitive_template import DAGNode, ExecutionTier
from src.models.execution import NodeResult, NodeStatus, ValidationResult
from src.executor.atomic_executor import AtomicExecutor
from src.executor.schema_validator import SchemaValidator

_log = get_logger(__name__)

# ─── Enums ────────────────────────────────────────────────────────────────────


class TriadRole(str):
    CREATOR = "creator"
    CYNIC = "cynic"
    RESOLVER = "resolver"


# ─── TriadResult ──────────────────────────────────────────────────────────────


class TriadResult:
    """Aggregated result from a full Creator → Cynic → Resolver run.

    Attributes:
        creator_output: Raw output from the Creator agent.
        cynic_critique: Parsed critique dict from the Cynic agent.
        resolver_output: Raw output from the Resolver agent.
        final_validated: Parsed and schema-validated resolver output.
        total_attempts: Number of triad iterations (fixed at 1 for now).
        succeeded: True if the resolver output passed validation.
    """

    def __init__(
        self,
        creator_output: str = "",
        cynic_critique: dict[str, Any] | None = None,
        resolver_output: str = "",
        final_validated: dict[str, Any] | None = None,
        total_attempts: int = 0,
        succeeded: bool = False,
    ) -> None:
        self.creator_output = creator_output
        self.cynic_critique = cynic_critique or {}
        self.resolver_output = resolver_output
        self.final_validated = final_validated
        self.total_attempts = total_attempts
        self.succeeded = succeeded


# ─── AdversarialTriad ─────────────────────────────────────────────────────────


class AdversarialTriad:
    """Sequential Creator → Cynic → Resolver reasoning pattern.

    Attributes:
        atomic_executor: AtomicExecutor for running Ollama calls.
        schema_validator: SchemaValidator for final output validation.
    """

    def __init__(
        self,
        atomic_executor: AtomicExecutor,
        schema_validator: SchemaValidator,
    ) -> None:
        self._executor = atomic_executor
        self._validator = schema_validator

    # ─── Creator ────────────────────────────────────────────────────────────────

    async def run_creator(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
    ) -> str:
        """Run the Creator agent — produce the best possible raw output.

        The Creator focuses purely on content quality, not validation.

        Args:
            node: The target DAGNode.
            global_state: Accumulated outputs from prior nodes.
            input_data: Top-level input payload.

        Returns:
            Raw output string from the Creator.
        """
        creator_prompt = node.focus_prompt.system_prompt
        # Augment with task-focused directive
        creator_system = (
            f"You are a {node.description} specialist. "
            "Write the best possible output. "
            "Focus entirely on content quality. "
            "Do not self-edit. Output only the requested content."
        )

        patched_node = node.model_copy(
            update={
                "focus_prompt": node.focus_prompt.model_copy(
                    update={"system_prompt": creator_system}
                )
            }
        )

        _log.debug("triad_creator_start", node_id=node.node_id)
        raw_output, rule_files = await self._executor.execute_node(
            node=patched_node,
            global_state=global_state,
            input_data=input_data,
            attempt_number=1,
            previous_error=None,
        )

        _log.info(
            "triad_creator_done",
            node_id=node.node_id,
            output_preview=raw_output[:100],
        )
        return raw_output

    # ─── Cynic ────────────────────────────────────────────────────────────────

    async def run_cynic(
        self,
        creator_output: str,
        node: DAGNode,
    ) -> dict[str, Any]:
        """Run the Cynic agent — identify the single most critical flaw.

        Args:
            creator_output: Raw output from the Creator.
            node: The DAGNode (for schema context).

        Returns:
            A critique dict: {"flaw": str, "severity": str, "location": str}.
        """
        cynic_system = (
            "You are a ruthless quality auditor. "
            "Find the single most critical flaw in the given output. "
            "Be precise and harsh. Output ONLY JSON."
        )

        cynic_user = (
            f"Review this output and identify its worst flaw:\n\n"
            f"{creator_output}\n\n"
            f"Output ONLY JSON in this exact format:\n"
            f'{{"flaw": "description of the flaw", "severity": "critical|major|minor", "location": "where in the output"}}'
        )

        patched_node = node.model_copy(
            update={
                "focus_prompt": node.focus_prompt.model_copy(
                    update={
                        "system_prompt": cynic_system,
                        "user_template": cynic_user,
                    }
                )
            }
        )

        _log.debug("triad_cynic_start", node_id=node.node_id)
        raw_output, _ = await self._executor.execute_node(
            node=patched_node,
            global_state={},
            input_data={},
            attempt_number=1,
            previous_error=None,
        )

        # Parse the critique JSON
        try:
            critique = json.loads(raw_output)
            if not all(k in critique for k in ("flaw", "severity", "location")):
                raise ValueError("Missing required keys")
        except Exception:
            _log.warning("cynic_critique_parse_failed", raw=raw_output[:200])
            critique = {
                "flaw": "unparseable output",
                "severity": "critical",
                "location": "entire output",
            }

        _log.info(
            "triad_cynic_done",
            node_id=node.node_id,
            flaw=critique.get("flaw", ""),
            severity=critique.get("severity", ""),
        )
        return critique

    # ─── Resolver ─────────────────────────────────────────────────────────────

    async def run_resolver(
        self,
        creator_output: str,
        critique: dict[str, Any],
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
    ) -> str:
        """Run the Resolver agent — fix only the identified flaw.

        Args:
            creator_output: Raw output from the Creator.
            critique: Parsed critique dict from the Cynic.
            node: The DAGNode.
            global_state: Accumulated outputs from prior nodes.
            input_data: Top-level input payload.

        Returns:
            Raw output string from the Resolver.
        """
        resolver_system = (
            "You are a precise technical editor. "
            "Fix ONLY the identified flaw. "
            "Do not rewrite anything else. "
            "Output ONLY the corrected version."
        )

        schema_json = json.dumps(node.focus_prompt.output_schema, indent=2)

        resolver_user = (
            f"Original output:\n{creator_output}\n\n"
            f"Identified flaw: {critique.get('flaw', 'unknown')} "
            f"(Location: {critique.get('location', 'unknown')})\n\n"
            f"Fix ONLY this flaw. "
            f"Output the corrected version as valid JSON matching this schema:\n"
            f"{schema_json}"
        )

        patched_node = node.model_copy(
            update={
                "focus_prompt": node.focus_prompt.model_copy(
                    update={
                        "system_prompt": resolver_system,
                        "user_template": resolver_user,
                    }
                )
            }
        )

        _log.debug("triad_resolver_start", node_id=node.node_id)
        raw_output, _ = await self._executor.execute_node(
            node=patched_node,
            global_state=global_state,
            input_data=input_data,
            attempt_number=1,
            previous_error=None,
        )

        _log.info(
            "triad_resolver_done",
            node_id=node.node_id,
            output_preview=raw_output[:100],
        )
        return raw_output

    # ─── Full triad execution ──────────────────────────────────────────────────

    async def execute_triad(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
    ) -> NodeResult:
        """Execute the full Creator → Cynic → Resolver triad.

        Args:
            node: The DAGNode to execute.
            global_state: Accumulated outputs from prior nodes.
            input_data: Top-level input payload.

        Returns:
            A NodeResult with tier_used=ExecutionTier.DEEP and
            a TriadResult stored in the metadata.
        """
        import time

        start_ms = time.perf_counter()

        # Stage 1: Creator
        creator_output = await self.run_creator(node, global_state, input_data)
        creator_ms = time.perf_counter() - start_ms

        # Stage 2: Cynic
        cynic_critique = await self.run_cynic(creator_output, node)
        cynic_ms = time.perf_counter() - start_ms - creator_ms

        # Stage 3: Resolver
        resolver_output = await self.run_resolver(
            creator_output, cynic_critique, node, global_state, input_data
        )
        resolver_ms = time.perf_counter() - start_ms - creator_ms - cynic_ms

        # Validate resolver output against schema
        validation = self._validator.validate_output(
            resolver_output, node.focus_prompt.output_schema
        )

        succeeded = validation.is_valid
        total_ms = (time.perf_counter() - start_ms) * 1000

        _log.info(
            "triad_complete",
            node_id=node.node_id,
            succeeded=succeeded,
            creator_time_ms=round(creator_ms * 1000, 2),
            cynic_time_ms=round(cynic_ms * 1000, 2),
            resolver_time_ms=round(resolver_ms * 1000, 2),
            total_time_ms=round(total_ms, 2),
        )

        triad_result = TriadResult(
            creator_output=creator_output,
            cynic_critique=cynic_critique,
            resolver_output=resolver_output,
            final_validated=validation.parsed_output,
            total_attempts=3,
            succeeded=succeeded,
        )

        return NodeResult(
            node_id=node.node_id,
            status=NodeStatus.PASSED_TIER3 if succeeded else NodeStatus.FAILED,
            tier_used=ExecutionTier.DEEP,
            raw_output=resolver_output,
            parsed_output=validation.parsed_output if succeeded else None,
            validation_result=validation,
            attempt_count=3,
            execution_time_ms=total_ms,
            rule_files_used=[],
            error_message=None if succeeded else "Resolver output failed validation",
        )
