"""Teacher client — calls a larger Ollama model to diagnose failures and prescribe fixes."""

import json
from typing import Any

import httpx

from src.core.config import SpecForgeConfig
from src.core.exceptions import HealingError, OllamaConnectionError
from src.core.logging import get_logger
from src.executor.atomic_executor import OllamaClient
from src.models.cognitive_template import DAGNode

_log = get_logger(__name__)

TEACHER_SYSTEM_PROMPT = (
    "You are an expert AI prompt engineer. Your job is to fix a broken rule file "
    "so that a smaller language model (4B parameters) can follow it reliably."
)


class TeacherClient:
    """Calls a larger Ollama model to diagnose node failures and prescribe rule patches.

    Uses the same OllamaClient interface but delegates to the teacher model
    (configured separately as OLLAMA_TEACHER_MODEL) for deep reasoning.

    Attributes:
        ollama_client: An OllamaClient configured with the teacher model.
    """

    def __init__(self, ollama_client: OllamaClient) -> None:
        self._client = ollama_client

    async def diagnose_and_prescribe(
        self,
        node: DAGNode,
        rule_file_name: str,
        original_rule_content: str,
        failure_examples: list[str],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Ask the teacher model to rewrite a rule file given failure examples.

        Args:
            node: The DAGNode that failed.
            rule_file_name: Name of the rule file to rewrite.
            original_rule_content: Current markdown content of the rule file.
            failure_examples: List of formatted failure strings.
            schema: The output JSON schema the node must satisfy.

        Returns:
            A dict with keys: rewritten_content, changes_made, root_cause.

        Raises:
            HealingError: If the teacher response is unparseable or invalid.
        """
        formatted_examples = "\n\n".join(
            f"{i + 1}. {ex}" for i, ex in enumerate(failure_examples)
        )

        user_prompt = f"""## Task
A small language model (4B parameters) is executing a task but repeatedly failing validation.

## Node Information
Node ID: {node.node_id}
Node Purpose: {node.description}
Output Schema Required: {json.dumps(schema, indent=2)}

## Current Rule File: {rule_file_name}
{original_rule_content}

## Failed Outputs ({len(failure_examples)} failures)
{formatted_examples}

## Your Task
Rewrite the rule file to prevent these specific failures. Apply these techniques:
1. Move the most critical constraint to the VERY TOP of the file
2. Add a "### ❌ What NOT to do" section with the exact failure as a negative example
3. Add a "### ✅ Correct Example" section with the expected JSON output
4. Bold or capitalize the most important constraint
5. Keep the file under 500 words — small models lose attention in long files

Output ONLY a JSON object:
{{
  "rewritten_content": "full new markdown content",
  "changes_made": ["list of changes as short strings"],
  "root_cause": "one sentence explaining why the model was failing"
}}"""

        try:
            raw_response = await self._client.generate(
                system_prompt=TEACHER_SYSTEM_PROMPT,
                user_message=user_prompt,
                max_tokens=2048,
                json_mode=True,
            )
        except OllamaConnectionError as exc:
            raise HealingError(
                node_id=node.node_id,
                failure_reason=f"Teacher model unreachable: {exc.base_url}",
                context={"rule_file": rule_file_name},
            ) from exc

        try:
            prescription = json.loads(raw_response)
            required_keys = {"rewritten_content", "changes_made", "root_cause"}
            if not required_keys.issubset(prescription.keys()):
                missing = required_keys - prescription.keys()
                raise HealingError(
                    node_id=node.node_id,
                    failure_reason=f"Teacher response missing keys: {missing}",
                    context={
                        "rule_file": rule_file_name,
                        "response_preview": raw_response[:200],
                    },
                )
            _log.info(
                "teacher_prescription_received",
                node_id=node.node_id,
                rule_file=rule_file_name,
                changes=prescription.get("changes_made", []),
            )
            return prescription

        except json.JSONDecodeError as exc:
            raise HealingError(
                node_id=node.node_id,
                failure_reason=f"Teacher response not valid JSON: {exc.msg}",
                context={
                    "rule_file": rule_file_name,
                    "response_preview": raw_response[:500],
                },
            ) from exc
