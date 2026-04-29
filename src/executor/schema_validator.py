"""Output validation and retry orchestration for atomic node execution."""

import json
import time
from typing import Any

import jsonschema

from src.core.logging import get_logger
from src.models.cognitive_template import DAGNode, ExecutionTier
from src.models.execution import NodeResult, NodeStatus, ValidationResult
from src.executor.atomic_executor import AtomicExecutor

_log = get_logger(__name__)

# ─── SchemaValidator ──────────────────────────────────────────────────────────


class SchemaValidator:
    """Validates node raw output against JSON parseability and jsonschema contract."""

    def __init__(self, max_retries: int = 3) -> None:
        self._max_retries = max_retries

    def validate_json(self, raw_output: str) -> tuple[bool, dict | None, list[str]]:
        """Attempt to parse raw_output as JSON.

        Args:
            raw_output: The raw string output from Ollama.

        Returns:
            Tuple of (success, parsed_dict_or_None, list_of_error_messages).
        """
        if not raw_output or not raw_output.strip():
            return False, None, ["Empty output"]

        try:
            parsed = json.loads(raw_output)
            if not isinstance(parsed, dict):
                return False, None, [f"Expected JSON object, got {type(parsed).__name__}"]
            return True, parsed, []
        except json.JSONDecodeError as exc:
            return False, None, [f"JSON parse error at line {exc.lineno}: {exc.msg}"]

    def validate_schema(
        self,
        parsed_output: dict[str, Any],
        json_schema: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate a parsed dict against a JSON Schema.

        Args:
            parsed_output: A dict parsed from the raw output.
            json_schema: A jsonschema-compatible schema dict.

        Returns:
            Tuple of (is_valid, list_of_error_messages).
        """
        if not json_schema:
            return True, []

        errors: list[str] = []
        try:
            jsonschema.validate(instance=parsed_output, schema=json_schema)
            return True, []
        except jsonschema.ValidationError as exc:
            errors.append(_simplify_jsonschema_error(exc))
            return False, errors
        except jsonschema.SchemaError as exc:
            errors.append(f"Invalid schema definition: {exc.message}")
            return False, errors

    def validate_output(
        self,
        raw_output: str,
        json_schema: dict[str, Any],
    ) -> ValidationResult:
        """Run full validation pipeline on raw output.

        Args:
            raw_output: The raw string output from Ollama.
            json_schema: A jsonschema schema dict to validate against.

        Returns:
            A ValidationResult model.
        """
        start = time.perf_counter()

        is_parseable, parsed, parse_errors = self.validate_json(raw_output)

        if not is_parseable:
            return ValidationResult(
                is_valid=False,
                errors=parse_errors,
                raw_output=raw_output,
                parsed_output=None,
                validation_time_ms=(time.perf_counter() - start) * 1000,
            )

        is_valid, schema_errors = self.validate_schema(parsed, json_schema)

        return ValidationResult(
            is_valid=is_valid,
            errors=parse_errors + schema_errors,
            raw_output=raw_output,
            parsed_output=parsed if is_valid else None,
            validation_time_ms=(time.perf_counter() - start) * 1000,
        )

    def build_repair_prompt(
        self,
        validation_result: ValidationResult,
        json_schema: dict[str, Any],
    ) -> str:
        """Generate a repair instruction to append to the retry prompt.

        Args:
            validation_result: The ValidationResult from the failed attempt.
            json_schema: The jsonschema that the output must satisfy.

        Returns:
            A formatted repair instruction string.
        """
        # Deduplicate errors so repair prompt stays clean
        unique_errors: list[str] = []
        seen: set[str] = set()
        for e in validation_result.errors:
            if e not in seen:
                seen.add(e)
                unique_errors.append(e)

        errors_str = "\n".join(f"- {e}" for e in unique_errors)
        schema_str = json.dumps(json_schema, indent=2) if json_schema else "No schema specified"

        return (
            "Your previous output was INVALID.\n"
            f"Errors:\n{errors_str}\n\n"
            f"Required schema:\n{schema_str}\n\n"
            "Output ONLY a valid JSON object matching this schema. No other text."
        )


# ─── RetryOrchestrator ─────────────────────────────────────────────────────────


class RetryOrchestrator:
    """3-tier retry execution: Fast → Repair → Deep (signal only)."""

    def __init__(
        self,
        atomic_executor: AtomicExecutor,
        schema_validator: SchemaValidator,
    ) -> None:
        self._executor = atomic_executor
        self._validator = schema_validator

    async def execute_with_retry(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
    ) -> NodeResult:
        """Execute a node with 3-tier retry strategy.

        Tier 1 (Fast): single attempt, validate, return.
        Tier 2 (Repair): retry with repair prompt if Tier 1 failed.
        Tier 3 (Deep): signal only — return FAILED with tier=DEEP
        so the caller (confidence_gate) can activate Adversarial Triad/Lookahead.

        Args:
            node: The DAGNode to execute.
            global_state: Accumulated outputs from prior executed nodes.
            input_data: Top-level input payload.

        Returns:
            A NodeResult with populated fields for the best attempt.
        """
        json_schema = node.focus_prompt.output_schema

        # ── TIER 1: Fast Path ────────────────────────────────────────────────

        raw_output, rule_files = await self._executor.execute_node(
            node=node,
            global_state=global_state,
            input_data=input_data,
            attempt_number=1,
            previous_error=None,
        )

        validation = self._validator.validate_output(raw_output, json_schema)

        if validation.is_valid:
            _log.info(
                "tier1_passed",
                node_id=node.node_id,
                attempt_count=1,
                tier_used=ExecutionTier.FAST.value,
            )
            return NodeResult(
                node_id=node.node_id,
                status=NodeStatus.PASSED_TIER1,
                tier_used=ExecutionTier.FAST,
                raw_output=raw_output,
                parsed_output=validation.parsed_output,
                validation_result=validation,
                attempt_count=1,
                execution_time_ms=validation.validation_time_ms,
                rule_files_used=rule_files,
                error_message=None,
            )

        _log.warning("tier1_failed", node_id=node.node_id)

        # ── TIER 2: Repair Path ────────────────────────────────────────────────

        repair_prompt = self._validator.build_repair_prompt(validation, json_schema)

        # Inject repair hint into global_state for the retry attempt
        retry_state = dict(global_state)
        retry_state["__repair_hint__"] = repair_prompt

        # Append repair hint to user_template if it doesn't already have it
        original_template = node.focus_prompt.user_template
        patched_template = (
            f"{original_template}\n\n{{__repair_hint__}}"
            if "__repair_hint__" not in original_template
            else original_template
        )

        # Build a patched node with the updated template
        patched_node = node.model_copy(
            update={
                "focus_prompt": node.focus_prompt.model_copy(
                    update={"user_template": patched_template}
                )
            }
        )

        raw_output_2, rule_files_2 = await self._executor.execute_node(
            node=patched_node,
            global_state=retry_state,
            input_data=input_data,
            attempt_number=2,
            previous_error="\n".join(validation.errors),
        )

        validation_2 = self._validator.validate_output(raw_output_2, json_schema)

        if validation_2.is_valid:
            _log.info(
                "tier2_passed",
                node_id=node.node_id,
                attempt_count=2,
                tier_used=ExecutionTier.REPAIR.value,
            )
            return NodeResult(
                node_id=node.node_id,
                status=NodeStatus.PASSED_TIER2,
                tier_used=ExecutionTier.REPAIR,
                raw_output=raw_output_2,
                parsed_output=validation_2.parsed_output,
                validation_result=validation_2,
                attempt_count=2,
                execution_time_ms=validation_2.validation_time_ms,
                rule_files_used=rule_files_2,
                error_message=None,
            )

        _log.warning("tier2_failed", node_id=node.node_id)

        # ── TIER 3: Deep Path — signal only ──────────────────────────────────

        # Show only the final tier's errors (deduplicated) so user sees the most relevant failure reason
        unique_errors: list[str] = []
        seen: set[str] = set()
        for e in validation_2.errors:
            if e not in seen:
                seen.add(e)
                unique_errors.append(e)

        _log.warning(
            "tier3_triggered",
            node_id=node.node_id,
            attempt_count=2,
            error_messages=unique_errors,
        )

        return NodeResult(
            node_id=node.node_id,
            status=NodeStatus.FAILED,
            tier_used=ExecutionTier.DEEP,
            raw_output=raw_output_2,
            parsed_output=None,
            validation_result=validation_2,
            attempt_count=2,
            execution_time_ms=validation_2.validation_time_ms,
            rule_files_used=rule_files_2,
            error_message=", ".join(unique_errors),
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _simplify_jsonschema_error(exc: jsonschema.ValidationError) -> str:
    """Reduce a verbose jsonschema.ValidationError to a one-line message."""
    if exc.path:
        path = ".".join(str(p) for p in exc.path)
        val = exc.instance
        if exc.validator == "minItems":
            actual = len(val) if isinstance(val, (list, tuple)) else val
            return f"At {path}: array has {actual} items, need at least {exc.validator_value}"
        if exc.validator == "maxItems":
            actual = len(val) if isinstance(val, (list, tuple)) else val
            return f"At {path}: array has {actual} items, max allowed is {exc.validator_value}"
        if exc.validator == "minLength":
            actual = len(val) if isinstance(val, str) else val
            return f"At {path}: string has {actual} chars, need at least {exc.validator_value}"
        if exc.validator == "maxLength":
            actual = len(val) if isinstance(val, str) else val
            return f"At {path}: string has {actual} chars, max allowed is {exc.validator_value}"
        if exc.validator == "minimum":
            return f"At {path}: value {val} is below minimum {exc.validator_value}"
        if exc.validator == "maximum":
            return f"At {path}: value {val} exceeds maximum {exc.validator_value}"
        if exc.validator == "required":
            missing = [str(p) for p in exc.path if p not in exc.instance]
            return f"At {path}: missing required fields: {', '.join(exc.validator_value)}"
        if exc.validator == "type":
            return f"At {path}: expected {exc.validator_value}, got {type(val).__name__}"
        return f"At {path}: {exc.message}"
    return exc.message
