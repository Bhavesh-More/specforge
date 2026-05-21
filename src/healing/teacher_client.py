"""Teacher client — calls a larger Ollama model to diagnose failures and prescribe fixes."""

import json
from typing import Any

from src.core.exceptions import HealingError, OllamaConnectionError
from src.core.logging import get_logger
from src.executor.atomic_executor import OllamaClient
from src.executor.schema_validator import extract_json_from_text
from src.models.cognitive_template import DAGNode
from src.quality.models import TeacherCritique
from src.quality.prompts import build_final_audit_prompt, build_teacher_critique_prompt

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

    def __init__(self, ollama_client: OllamaClient, model: str) -> None:
        self._client = ollama_client
        self._model = model
        # Re-create client with teacher model
        self._client.model = model

    async def critique_successful_output(
        self,
        *,
        template_name: str,
        node: DAGNode,
        original_task: str,
        current_output: str,
        output_schema: dict[str, Any],
        quality_dimensions: list[str],
        memory_context: str = "",
    ) -> TeacherCritique:
        """Ask the teacher to score and critique a successful local output.

        This path is best-effort: malformed teacher responses should not turn a
        successful execution into a failure.
        """
        prompt = build_teacher_critique_prompt(
            template_name=template_name,
            node_id=node.node_id,
            node_description=node.description,
            node_type=getattr(node.node_type, "value", str(node.node_type)),
            original_task=original_task,
            current_output=current_output,
            output_schema=output_schema,
            quality_dimensions=quality_dimensions,
            memory_context=memory_context,
        )
        try:
            raw_response = await self._client.generate(
                system_prompt=(
                    "You are a strict senior AI evaluator. Return only valid JSON."
                ),
                user_message=prompt,
                max_tokens=1200,
                json_mode=True,
            )
            parsed = _parse_json_object(raw_response)
            if parsed is None:
                raise ValueError("teacher critique response was not a JSON object")
            return TeacherCritique(**parsed)
        except Exception as exc:
            _log.warning(
                "teacher_success_critique_unavailable",
                node_id=node.node_id,
                error=str(exc),
            )
            return TeacherCritique(
                quality_score=0.5,
                should_revise=False,
                concise_summary="Teacher critique unavailable",
            )

    async def audit_final_output(
        self,
        *,
        template_name: str,
        user_input: dict[str, Any],
        final_output: dict[str, Any],
        memory_context: str = "",
    ) -> dict[str, Any]:
        """Teacher audits cross-node consistency of final output."""
        prompt = build_final_audit_prompt(
            template_name=template_name,
            user_input=user_input,
            final_output=final_output,
            memory_context=memory_context,
        )
        try:
            raw_response = await self._client.generate(
                system_prompt=(
                    "You are a strict final QA auditor for structured AI outputs. "
                    "Return only valid JSON."
                ),
                user_message=prompt,
                max_tokens=1200,
                json_mode=True,
            )
            parsed = _parse_json_object(raw_response)
            if parsed is None:
                raise ValueError("teacher final audit response was not JSON")
            return {
                "quality_score": float(parsed.get("quality_score", 0.5)),
                "audit_notes": list(parsed.get("audit_notes") or []),
                "consistency_issues": list(parsed.get("consistency_issues") or []),
                "missing_details": list(parsed.get("missing_details") or []),
                "rewrite_instructions": list(parsed.get("rewrite_instructions") or []),
                "should_rewrite": bool(parsed.get("should_rewrite", False)),
            }
        except Exception as exc:
            _log.warning("teacher_final_audit_unavailable", error=str(exc))
            return {
                "quality_score": 0.5,
                "audit_notes": ["Teacher final audit unavailable"],
                "consistency_issues": [],
                "missing_details": [],
                "rewrite_instructions": [],
                "should_rewrite": False,
            }

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


def _parse_json_object(raw_response: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw_response)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        extracted = extract_json_from_text(raw_response)
        if not extracted:
            return None
        try:
            parsed = json.loads(extracted)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
