"""Bento Box micro-context assembly — the per-node context firewall."""

import json
import re
from pathlib import Path
from typing import Any

import aiofiles

from src.core.exceptions import NodeExecutionError
from src.core.logging import get_logger
from src.models.cognitive_template import DAGNode

_log = get_logger(__name__)

WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


def estimate_tokens(text: str) -> int:
    """Estimate token count from text using character approximation.

    Args:
        text: Raw string content.

    Returns:
        Estimated token count (len / 4).
    """
    return len(text) // 4


class ContextSurgeon:
    """Per-node Bento Box context assembler.

    Loads rule files, follows wiki-links, respects token budgets, and
    interpolates variables into node prompts.

    Attributes:
        rules_dir: Path to the rules/ directory containing .md rule files.
        token_budget: Default max tokens across all assembled rule content.
    """

    def __init__(self, rules_dir: Path, token_budget: int = 1500) -> None:
        self._rules_dir = rules_dir
        self._default_budget = token_budget
        self._rule_cache: dict[str, str] = {}

    # ─── Load rule files ────────────────────────────────────────────────────────

    async def load_rule_file(self, file_name: str) -> str:
        """Load a rule .md file from rules_dir.

        Handles both bare names (``python_rules``) and explicit extensions
        (``python_rules.md``).

        Args:
            file_name: Base name of the rule file.

        Returns:
            File content as a string, or empty string if the file does not exist.
            A warning is logged for missing files.
        """
        if file_name in self._rule_cache:
            return self._rule_cache[file_name]

        name = file_name if file_name.endswith(".md") else f"{file_name}.md"
        path = self._rules_dir / name

        if not path.is_file():
            _log.warning("rule_file_not_found", file_name=file_name, path=str(path))
            return ""

        async with aiofiles.open(path, "r", encoding="utf-8") as fh:
            content = await fh.read()

        self._rule_cache[file_name] = content
        _log.debug("rule_file_loaded", file_name=file_name, size=len(content))
        return content

    # ─── Wiki-link traversal ───────────────────────────────────────────────────

    async def follow_wiki_links(
        self,
        content: str,
        current_depth: int,
        max_depth: int,
    ) -> list[str]:
        """Parse and recursively load [[wiki-link]] targets.

        Args:
            content: Raw markdown content to scan for [[link_name]] patterns.
            current_depth: Current recursion depth.
            max_depth: Maximum recursion depth (from bento_config.max_depth).

        Returns:
            List of loaded file content strings.
        """
        if current_depth >= max_depth:
            return []

        linked_contents: list[str] = []
        names = WIKI_LINK_PATTERN.findall(content)

        for name in names:
            # Strip anchors (e.g. "Rule Name#section" -> "Rule Name")
            clean = name.split("#")[0].strip()
            file_content = await self.load_rule_file(clean)
            if not file_content:
                continue

            linked_contents.append(file_content)

            # Recurse if within depth limit
            if current_depth + 1 < max_depth:
                deeper = await self.follow_wiki_links(
                    file_content,
                    current_depth + 1,
                    max_depth,
                )
                linked_contents.extend(deeper)

        return linked_contents

    # ─── Bento Box assembly ────────────────────────────────────────────────────

    async def assemble_bento_box(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Assemble a complete Bento Box context for a given node.

        Args:
            node: The DAGNode being prepared.
            global_state: Accumulated output dict from prior executed nodes.
            input_data: Top-level input payload for this execution run.

        Returns:
            A Bento Box context dict with keys:
            - rule_content (str): assembled rule markdown
            - variables (dict): merged and flattened variable dict for interpolation
            - rule_files_used (list[str]): names of loaded rule files
            - token_estimate (int): estimated total token count
            - truncated (bool): True if token budget was exceeded

        Raises:
            NodeExecutionError: If a required variable is missing from context.
        """
        bento = node.bento_config
        token_budget = bento.token_budget or self._default_budget

        # Load primary rule files
        rule_files_used: list[str] = []
        all_rule_content: list[str] = []
        total_tokens = 0

        for file_name in bento.rule_files:
            content = await self.load_rule_file(file_name)
            if content:
                rule_files_used.append(file_name)
                all_rule_content.append(content)
                total_tokens += estimate_tokens(content)

        # Follow wiki-links if enabled
        if bento.follow_links:
            for file_name in list(rule_files_used):
                primary_content = self._rule_cache.get(file_name, "")
                if primary_content:
                    linked = await self.follow_wiki_links(
                        primary_content,
                        current_depth=0,
                        max_depth=bento.max_depth,
                    )
                    for linked_content in linked:
                        if total_tokens + estimate_tokens(linked_content) > token_budget:
                            _log.warning(
                                "bento_box_truncated",
                                node_id=node.node_id,
                                file_name=file_name,
                                token_budget=token_budget,
                            )
                            break
                        all_rule_content.append(linked_content)
                        total_tokens += estimate_tokens(linked_content)

        # Enforce token budget across all accumulated content
        truncated_rule_content: list[str] = []
        running_tokens = 0
        truncated = False

        for chunk in all_rule_content:
            chunk_tokens = estimate_tokens(chunk)
            if running_tokens + chunk_tokens > token_budget:
                truncated = True
                _log.warning(
                    "bento_box_token_budget_exceeded",
                    node_id=node.node_id,
                    budget=token_budget,
                    used_before_chunk=running_tokens,
                    chunk_tokens=chunk_tokens,
                )
                break
            truncated_rule_content.append(chunk)
            running_tokens += chunk_tokens

        rule_content = "\n\n".join(truncated_rule_content)

        # Merge variables: input_data is the base, global_state takes precedence
        combined: dict[str, Any] = {}
        combined.update(input_data)
        combined.update(global_state)

        # Flatten into dot-notation keys for interpolation
        flat = self._flatten_variables(combined)

        # Check required_variables against the flat namespace so that
        # references like "metadata.title" are validated here, not later
        for var in node.focus_prompt.required_variables:
            if var not in flat:
                raise NodeExecutionError(
                    node_id=node.node_id,
                    attempt_count=0,
                    last_output="",
                    context={
                        "missing_variable": var,
                        "available_keys": list(flat.keys()),
                    },
                )

        _log.info(
            "bento_box_assembled",
            node_id=node.node_id,
            rule_files_loaded=rule_files_used,
            token_estimate=running_tokens,
            truncated=truncated,
        )

        return {
            "rule_content": rule_content,
            "variables": flat,
            "rule_files_used": rule_files_used,
            "token_estimate": running_tokens,
            "truncated": truncated,
        }

    # ─── Variable flattening ───────────────────────────────────────────────────

    def _flatten_variables(
        self, variables: dict[str, Any], prefix: str = ""
    ) -> dict[str, Any]:
        """Recursively flatten nested dicts into dot-notation keys.

        Example::

            {"metadata": {"title": "Bug", "component": "auth"}}
            →
            {
                "metadata":           {"title": "Bug", "component": "auth"},
                "metadata.title":     "Bug",
                "metadata.component": "auth",
            }

        Lists are kept as-is at their own key; they are serialised to JSON
        when substituted into a template.

        Args:
            variables: Possibly nested dict to flatten.
            prefix: Dot-separated key prefix accumulated during recursion.

        Returns:
            Flat dict with dot-notation keys at every nesting level.
        """
        flat: dict[str, Any] = {}
        for key, value in variables.items():
            full_key = f"{prefix}.{key}" if prefix else key
            flat[full_key] = value
            if isinstance(value, dict):
                flat.update(self._flatten_variables(value, prefix=full_key))
        return flat

    # ─── Prompt interpolation ──────────────────────────────────────────────────

    def interpolate_prompt(
        self,
        template: str,
        variables: dict[str, Any],
        node_id: str = "",
    ) -> str:
        """Replace ``{variable}`` and ``{nested.key}`` patterns in a template.

        Variables are expected to already be flattened (output of
        ``_flatten_variables``). Nested values (dict / list) are serialised
        to indented JSON before substitution.

        Args:
            template: String containing ``{key}`` placeholders.
            variables: Flat dict produced by ``_flatten_variables``.
            node_id: Node identifier used in error reporting.

        Returns:
            Fully interpolated string.

        Raises:
            NodeExecutionError: If a placeholder key is not found in variables.
        """

        def replacer(match: re.Match) -> str:  # type: ignore[type-arg]
            key = match.group(1)
            if key not in variables:
                raise NodeExecutionError(
                    node_id=node_id,
                    attempt_count=0,
                    last_output="",
                    context={
                        "missing_variable": key,
                        "available_keys": list(variables.keys()),
                    },
                )
            value = variables[key]
            if isinstance(value, (dict, list)):
                return json.dumps(value, indent=2)
            return str(value)

        return re.sub(r"\{([^{}]+)\}", replacer, template)

    # ─── Build final prompt ─────────────────────────────────────────────────────

    async def build_final_prompt(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
    ) -> tuple[str, str, list[str]]:
        """Assemble the full system_prompt and user_message for a node.

        Args:
            node: The target DAGNode.
            global_state: Accumulated outputs from previously executed nodes.
            input_data: Top-level execution input payload.

        Returns:
            Tuple of (system_prompt, user_message, rule_files_used).
        """
        bento = await self.assemble_bento_box(node, global_state, input_data)

        system_prompt = node.focus_prompt.system_prompt
        if bento["rule_content"]:
            system_prompt = f"{system_prompt}\n\n## Rules\n{bento['rule_content']}"

        user_message = self.interpolate_prompt(
            node.focus_prompt.user_template,
            bento["variables"],
            node_id=node.node_id,
        )

        return system_prompt, user_message, bento["rule_files_used"]