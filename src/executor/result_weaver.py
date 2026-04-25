"""Result Weaver — assembles final output and maintains the Glass-Box state.md."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from src.core.logging import get_logger
from src.models.cognitive_template import CognitiveTemplate, DAGNode
from src.models.execution import ExecutionRun, NodeResult, NodeStatus

_log = get_logger(__name__)

NODE_SECTION_PATTERN = re.compile(
    r"##\s+\[?[^\]]+\]?\s+(?P<node_id>\S+)\s*\n.*?```json\n(?P<json_block>.*?)```",
    re.DOTALL,
)

STATUS_EMOJI = {
    NodeStatus.PASSED_TIER1: "✅",
    NodeStatus.PASSED_TIER2: "⚠️",
    NodeStatus.PASSED_TIER3: "🔄",
    NodeStatus.FAILED: "❌",
    NodeStatus.PENDING: "⏳",
    NodeStatus.RUNNING: "🔄",
}


class StateFileWriter:
    """Maintains the Glass-Box execution state.md for a single run.

    Attributes:
        state_file_path: Path to the state.md file to write.
    """

    def __init__(self, state_file_path: Path) -> None:
        self._path = state_file_path

    async def initialize(
        self,
        run: ExecutionRun,
        template: CognitiveTemplate,
    ) -> None:
        """Create or overwrite state.md with the execution header.

        Args:
            run: The ExecutionRun being executed.
            template: The CognitiveTemplate being run.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        header = (
            f"# SpecForge Execution — {template.name}\n"
            f"**Run ID:** {run.run_id}\n"
            f"**Started:** {timestamp}\n"
            f"**Status:** RUNNING\n\n---\n\n"
        )
        async with aiofiles.open(self._path, "w", encoding="utf-8") as fh:
            await fh.write(header)
        _log.info("state_file_initialized", run_id=run.run_id, path=str(self._path))

    async def append_node_result(self, node: DAGNode, result: NodeResult) -> None:
        """Append a node result section to state.md.

        Args:
            node: The DAGNode that executed.
            result: Its NodeResult.
        """
        status_emoji = STATUS_EMOJI.get(result.status, "❓")
        status_line = f"{result.status.value}"
        tier_line = result.tier_used.value
        ms = round(result.execution_time_ms, 2)
        rules = ", ".join(result.rule_files_used) if result.rule_files_used else "none"

        if result.status == NodeStatus.FAILED:
            output_block = f"**Error:** {result.error_message or 'Unknown error'}"
        else:
            parsed = result.parsed_output
            output_json = json.dumps(parsed, indent=2) if parsed else "{}"
            output_block = f"```json\n{output_json}\n```"

        section = (
            f"## {node.name} [{status_emoji}] {node.node_id}\n"
            f"**Status:** {status_line} | "
            f"**Tier:** {tier_line} | "
            f"**Time:** {ms}ms | "
            f"**Attempts:** {result.attempt_count}\n"
            f"**Rules Used:** {rules}\n\n"
            f"### Output\n{output_block}\n\n---\n\n"
        )

        async with aiofiles.open(self._path, "a", encoding="utf-8") as fh:
            await fh.write(section)

        _log.info(
            "node_result_appended",
            node_id=node.node_id,
            status=result.status.value,
            path=str(self._path),
        )

    async def finalize(self, run: ExecutionRun, success: bool) -> None:
        """Append the final summary footer and update the status line.

        Args:
            run: The completed ExecutionRun.
            success: True if COMPLETED, False if FAILED.
        """
        final_status = "COMPLETED" if success else "FAILED"
        timestamp = datetime.now(timezone.utc).isoformat()
        total_ms = run.total_execution_time_ms
        total_time = f"{round(total_ms, 2)}ms" if total_ms else "N/A"

        summary = (
            f"\n---\n\n"
            f"## Execution Summary\n"
            f"**Status:** {final_status}\n"
            f"**Completed:** {timestamp}\n"
            f"**Total Time:** {total_time}\n"
            f"**Run ID:** {run.run_id}\n"
        )

        # Read current content, update status line, append summary
        if self._path.exists():
            async with aiofiles.open(self._path, "r", encoding="utf-8") as fh:
                content = await fh.read()
            
        else:
            content = ""

        # Update the status badge in the header
        content = re.sub(
            r"\*\*Status:\*\*\s*\w+",
            f"**Status:** {final_status}",
            content,
            count=1,
        )
        content = content + summary

        async with aiofiles.open(self._path, "w", encoding="utf-8") as fh:
            await fh.write(content)

        _log.info(
            "state_file_finalized",
            run_id=run.run_id,
            success=success,
            path=str(self._path),
        )

    async def read_node_output_from_state(self, node_id: str) -> dict[str, Any] | None:
        """Find and parse the JSON output block for a node in state.md.

        Supports human-in-the-loop: if a human edited state.md, this reads
        their corrected output.

        Args:
            node_id: The node ID to search for.

        Returns:
            Parsed JSON dict from the node's output block, or None if not found.
        """
        if not self._path.exists():
            return None

        async with aiofiles.open(self._path, "r", encoding="utf-8") as fh:
            content = await fh.read()

        # Find section for this node_id
        for match in NODE_SECTION_PATTERN.finditer(content):
            if match.group("node_id") == node_id:
                raw = match.group("json_block").strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    _log.warning(
                        "state_file_human_edit_parse_failed",
                        node_id=node_id,
                    )
                    return None

        return None


class ResultWeaver:
    """Assembles global state and final output from individual node results.

    Attributes:
        state_writer: The StateFileWriter for this execution run.
    """

    def __init__(self, state_writer: StateFileWriter) -> None:
        self._writer = state_writer

    def update_global_state(
        self,
        global_state: dict[str, Any],
        node: DAGNode,
        node_result: NodeResult,
    ) -> dict[str, Any]:
        """Merge a node's parsed output into the global state dict.

        Successful nodes contribute their output_key → parsed_output.
        Failed nodes do not update the global state.

        Args:
            global_state: Accumulated state dict from prior nodes.
            node: The DAGNode that produced this result.
            node_result: Its NodeResult.

        Returns:
            Updated global_state dict.
        """
        if node_result.status in {
            NodeStatus.PASSED_TIER1,
            NodeStatus.PASSED_TIER2,
            NodeStatus.PASSED_TIER3,
        }:
            if node_result.parsed_output is not None:
                global_state[node.output_key] = node_result.parsed_output
                _log.debug(
                    "global_state_updated",
                    node_id=node.node_id,
                    output_key=node.output_key,
                )

        return global_state

    def assemble_final_output(
        self,
        global_state: dict[str, Any],
        template: CognitiveTemplate,
        execution_run: ExecutionRun,
    ) -> dict[str, Any]:
        """Build the final output dict from all node results plus metadata.

        Args:
            global_state: Accumulated output dict keyed by node output_key.
            template: The CognitiveTemplate that was executed.
            execution_run: The completed ExecutionRun.

        Returns:
            Final output dict with all node outputs and _specforge_meta.
        """
        # Collect all rule files used across all nodes
        all_rules: set[str] = set()
        for result in execution_run.node_results.values():
            all_rules.update(result.rule_files_used)

        meta = {
            "_specforge_meta": {
                "run_id": execution_run.run_id,
                "template_id": execution_run.template_id,
                "template_name": execution_run.template_name,
                "status": execution_run.status.value,
                "total_execution_time_ms": execution_run.total_execution_time_ms,
                "rules_used": sorted(all_rules),
            }
        }

        output = dict(global_state)
        output.update(meta)

        _log.info("final_output_assembled", run_id=execution_run.run_id)
        return output

    async def check_for_human_edits(
        self,
        node_id: str,
        original_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Detect and return human edits to a node's output in state.md.

        If the human-modified output differs from the original model output,
        the human edit wins.

        Args:
            node_id: The node ID to check.
            original_output: The model-produced output dict.

        Returns:
            The output dict — original if no human edit, human-edited if different.
        """
        edited = await self._writer.read_node_output_from_state(node_id)

        if edited is None:
            return original_output

        if edited != original_output:
            _log.warning(
                "human_edit_detected",
                node_id=node_id,
            )

        return edited if edited is not None else original_output
