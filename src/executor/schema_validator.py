"""Output validation and retry orchestration for atomic node execution."""

import json
import re
import time
from typing import Any

import jsonschema

from src.core.logging import get_logger
from src.models.cognitive_template import DAGNode, ExecutionTier, NodeType
from src.models.execution import NodeResult, NodeStatus, ValidationResult
from src.executor.atomic_executor import AtomicExecutor

_log = get_logger(__name__)


# ─── Helpers ───────────────────────────────────────────────────────────────────


def extract_json_from_text(text: str) -> str | None:
    """Extract JSON object from text that may contain prose or markdown.

    Attempts to find a JSON object (starting with { and ending with }) in the text.
    Useful for models that wrap their JSON response in markdown or explanation.

    Args:
        text: The raw text that may contain JSON.

    Returns:
        The JSON string if found, None otherwise.
    """
    # Try to find JSON wrapped in markdown code blocks
    markdown_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if markdown_match:
        return markdown_match.group(1)

    # Try to find a top-level JSON object
    # Find the first { and match it with the last }
    start_idx = text.find("{")
    if start_idx >= 0:
        # Count braces to find the matching closing }
        brace_count = 0
        for i, char in enumerate(text[start_idx:], start=start_idx):
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return text[start_idx : i + 1]
    
    return None


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

        # Try direct parse first
        try:
            parsed = json.loads(raw_output)
            if not isinstance(parsed, dict):
                return False, None, [f"Expected JSON object, got {type(parsed).__name__}"]
            return True, parsed, []
        except json.JSONDecodeError as exc:
            # Log first 200 chars of actual output for debugging
            preview = raw_output[:200] if len(raw_output) > 200 else raw_output
            _log.warning(
                "json_parse_failed",
                error=exc.msg,
                line=exc.lineno,
                output_preview=preview,
                output_length=len(raw_output),
            )
            
            # Try to extract JSON from text (wrapped in markdown, prose, etc)
            extracted = extract_json_from_text(raw_output)
            if extracted:
                try:
                    parsed = json.loads(extracted)
                    if isinstance(parsed, dict):
                        _log.info(
                            "json_extracted_from_text",
                            original_length=len(raw_output),
                            extracted_length=len(extracted),
                        )
                        return True, parsed, []
                except json.JSONDecodeError:
                    pass  # Fall through to error
            
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

        hydrated = _hydrate_required_defaults(parsed, json_schema)
        # Apply lightweight post-processing repairs to tolerate small model formatting issues
        repaired = _post_process_repair(hydrated, json_schema)
        is_valid, schema_errors = self.validate_schema(repaired, json_schema)

        return ValidationResult(
            is_valid=is_valid,
            errors=parse_errors + schema_errors,
            raw_output=raw_output,
            parsed_output=repaired if is_valid else None,
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

        # If this node is explicitly a deep_reason node, we treat the
        # reasoning output as free-form text and DO NOT attempt JSON
        # parsing/validation here. Wrap the free-form text into a simple
        # parsed_output dict so downstream nodes can reference
        # `{node.output_key}.analysis_text`.
        if getattr(node, "node_type", None) == NodeType.DEEP_REASON:
            _log.info("tier1_deep_reason_passthrough", node_id=node.node_id)
            parsed = {"analysis_text": raw_output}
            validation = ValidationResult(
                is_valid=True,
                errors=[],
                raw_output=raw_output,
                parsed_output=parsed,
                validation_time_ms=0.0,
            )
            return NodeResult(
                node_id=node.node_id,
                status=NodeStatus.PASSED_TIER1,
                tier_used=ExecutionTier.FAST,
                raw_output=raw_output,
                parsed_output=parsed,
                validation_result=validation,
                attempt_count=1,
                execution_time_ms=0.0,
                rule_files_used=rule_files,
                error_message=None,
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


def _default_for_schema_type(schema: dict[str, Any]) -> Any:
    """Return a conservative default value for a schema property type."""
    type_name = schema.get("type")
    if isinstance(type_name, list):
        type_name = next((t for t in type_name if t != "null"), type_name[0] if type_name else None)

    if type_name == "string":
        return "unknown"
    if type_name == "number":
        return 0.0
    if type_name == "integer":
        return 0
    if type_name == "boolean":
        return False
    if type_name == "array":
        return []
    if type_name == "object":
        return {}
    return None


def _hydrate_required_defaults(
    parsed_output: dict[str, Any],
    json_schema: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing required top-level properties with type-safe defaults.

    This makes execution resilient when the model omits one or two fields that can
    safely default (e.g. string fields become "unknown").
    """
    # Recursive hydrator: fills missing required properties at any object depth
    def _hydrate(obj: Any, schema: dict[str, Any]) -> Any:
        if not schema or obj is None:
            return obj

        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            # prefer non-null type
            schema_type = next((t for t in schema_type if t != "null"), schema_type[0])

        # Only handle objects (dicts)
        if schema_type == "object":
            props = schema.get("properties", {}) or {}
            required = schema.get("required", []) or []
            obj_dict = dict(obj) if isinstance(obj, dict) else {}

            # Fill missing required properties with conservative defaults
            for key in required:
                if key not in obj_dict:
                    prop_schema = props.get(key, {})
                    if isinstance(prop_schema, dict):
                        obj_dict[key] = _default_for_schema_type(prop_schema)

            # Recurse into present properties that are objects
            for key, prop_schema in props.items():
                if key in obj_dict and isinstance(prop_schema, dict):
                    if prop_schema.get("type") == "object" and isinstance(obj_dict.get(key), dict):
                        obj_dict[key] = _hydrate(obj_dict.get(key), prop_schema)
                    else:
                        # If string and empty, fill default for robustness
                        if prop_schema.get("type") == "string" and isinstance(obj_dict.get(key), str):
                            if not obj_dict.get(key).strip():
                                obj_dict[key] = _default_for_schema_type(prop_schema)

            return obj_dict

        # For non-object types, return as-is
        return obj

    return _hydrate(parsed_output, json_schema)


def _post_process_repair(parsed_output: dict[str, Any], json_schema: dict[str, Any]) -> dict[str, Any]:
    """Apply small, conservative repairs to parsed output to tolerate common model mistakes.

    Repairs performed:
    - Replace empty strings for required string fields with conservative defaults ("unknown").
    - If top-level required `summary` is missing or is an object, try to extract a usable
      summary from nested fields (e.g., `summary.summary`, `recommended_fix.fix[0].name`).
    """
    if not isinstance(parsed_output, dict) or not isinstance(json_schema, dict):
        return parsed_output

    repaired = dict(parsed_output)
    properties = json_schema.get("properties", {}) or {}
    required = json_schema.get("required", []) or []

    # Fill empty string values for required properties (top-level and simple nested cases)
    for key in required:
        if key in repaired:
            val = repaired[key]
            prop_schema = properties.get(key, {}) or {}
            if isinstance(val, str) and not val.strip():
                if prop_schema.get("type") == "string":
                    repaired[key] = _default_for_schema_type(prop_schema)

            # handle common nested object case where summary is returned as object
            if key == "summary" and isinstance(val, dict):
                # try common nested locations
                if isinstance(val.get("summary"), str) and val.get("summary").strip():
                    repaired[key] = val.get("summary").strip()
                else:
                    # try recommended_fix -> fixes[0] -> name
                    rf = val.get("recommended_fix") or val.get("recommended_fix")
                    if isinstance(rf, dict):
                        fixes = rf.get("fixes") or rf.get("fixes")
                        if isinstance(fixes, list) and fixes:
                            first = fixes[0]
                            if isinstance(first, dict) and isinstance(first.get("name"), str):
                                repaired[key] = f"Recommended: {first.get('name')}"

    # More aggressive extraction: search common nested keys for a usable summary string.
    def _find_string_by_keys(obj: Any, candidate_keys: list[str]) -> str | None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in candidate_keys and isinstance(v, str) and v.strip():
                    return v.strip()
                # recurse
                found = _find_string_by_keys(v, candidate_keys)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _find_string_by_keys(item, candidate_keys)
                if found:
                    return found
        return None

    summary_keys = ["summary", "text", "description", "message", "executive_summary"]
    # If top-level summary is required but missing/empty, try to extract from anywhere in the payload
    if "summary" in required and ("summary" not in repaired or not isinstance(repaired.get("summary"), str) or not repaired.get("summary").strip()):
        # Try a few candidate sources in order: root_cause.root_cause, proposed_fixes fixes[].name, or any common text fields.
        rc = repaired.get("root_cause")
        if isinstance(rc, dict) and isinstance(rc.get("root_cause"), str) and rc.get("root_cause").strip():
            repaired["summary"] = rc.get("root_cause").strip()
        else:
            # try proposed_fixes
            pf = repaired.get("proposed_fixes") or repaired.get("proposed_fix") or repaired.get("proposed_fixes")
            if isinstance(pf, dict):
                fixes = pf.get("fixes")
                if isinstance(fixes, list) and fixes:
                    name = fixes[0].get("name") if isinstance(fixes[0], dict) else None
                    if isinstance(name, str) and name.strip():
                        repaired["summary"] = f"Recommended: {name.strip()}"
        # fallback: search entire payload for any common summary-like fields
        if "summary" not in repaired or not isinstance(repaired.get("summary"), str) or not repaired.get("summary").strip():
            found = _find_string_by_keys(repaired, summary_keys)
            if found:
                repaired["summary"] = found

    # Synthesize or repair `severity.reasoning` when required but empty
    # If the schema expects a nested object with a `reasoning` string, try to fill it.
    try:
        sev_prop = properties.get("severity") or {}
        if isinstance(sev_prop, dict):
            sev_required = sev_prop.get("required", []) or []
            if "reasoning" in sev_required:
                sev = repaired.get("severity")
                if isinstance(sev, dict):
                    reasoning_val = sev.get("reasoning")
                    if not (isinstance(reasoning_val, str) and reasoning_val.strip()):
                        # prefer root_cause text
                        rc = repaired.get("root_cause")
                        if isinstance(rc, dict) and isinstance(rc.get("root_cause"), str) and rc.get("root_cause").strip():
                            sev["reasoning"] = rc.get("root_cause").strip()
                        else:
                            # try first reproduction step action
                            repro = repaired.get("reproduction")
                            if isinstance(repro, dict):
                                steps = repro.get("steps")
                                if isinstance(steps, list) and steps:
                                    first = steps[0]
                                    if isinstance(first, dict) and isinstance(first.get("action"), str):
                                        sev["reasoning"] = f"Based on reproduction step: {first.get('action').strip()}"
                                    else:
                                        # try proposed_fixes approaches
                                        pf = repaired.get("proposed_fixes") or repaired.get("proposed_fix")
                                        if isinstance(pf, dict):
                                            fixes = pf.get("fixes")
                                            if isinstance(fixes, list) and fixes:
                                                approach = fixes[0].get("approach") if isinstance(fixes[0], dict) else None
                                                if isinstance(approach, str) and approach.strip():
                                                    sev["reasoning"] = f"Suggested fix approach: {approach.strip()}"
                        repaired["severity"] = sev
    except Exception:
        # be conservative: don't raise on repair attempts
        pass

    def _schema_allows_type(schema: dict[str, Any], type_name: str) -> bool:
        if not isinstance(schema, dict):
            return False

        # Handle composition keywords used heavily in template schemas.
        for key in ("anyOf", "oneOf", "allOf"):
            options = schema.get(key)
            if isinstance(options, list):
                return any(
                    isinstance(opt, dict) and _schema_allows_type(opt, type_name)
                    for opt in options
                )

        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            return type_name in schema_type
        return schema_type == type_name

    def _object_satisfies_required(value: Any, schema: dict[str, Any]) -> bool:
        if not isinstance(value, dict):
            return False
        required = schema.get("required")
        if not isinstance(required, list):
            return True
        return all(key in value for key in required)

    def _coerce_value_to_string(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            # Preserve concise incident artifact semantics when available.
            artifact_type = value.get("artifact_type")
            source_name = value.get("source_name")
            details = value.get("details")
            if isinstance(artifact_type, str) and artifact_type.strip():
                parts = [artifact_type.strip()]
                if isinstance(source_name, str) and source_name.strip():
                    parts.append(f"source={source_name.strip()}")
                if isinstance(details, str) and details.strip():
                    parts.append(f"details={details.strip()}")
                return " | ".join(parts)
        # Fallback to compact JSON so structure is not lost.
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)

    def _repair_by_schema(value: Any, schema: dict[str, Any]) -> Any:
        if not isinstance(schema, dict):
            return value

        # Resolve composition schemas conservatively.
        for key in ("anyOf", "oneOf"):
            options = schema.get(key)
            if isinstance(options, list) and options:
                if isinstance(value, str):
                    # Strings are already acceptable if any branch allows string.
                    if any(isinstance(opt, dict) and _schema_allows_type(opt, "string") for opt in options):
                        return value

                if isinstance(value, dict):
                    # Keep object only when it satisfies an object branch's required keys.
                    for opt in options:
                        if isinstance(opt, dict) and _schema_allows_type(opt, "object"):
                            if _object_satisfies_required(value, opt):
                                return _repair_by_schema(value, opt)

                    # Object is malformed for object branches; if string branch exists, coerce.
                    if any(isinstance(opt, dict) and _schema_allows_type(opt, "string") for opt in options):
                        return _coerce_value_to_string(value)

                # Primitive mismatch with available string branch.
                if any(isinstance(opt, dict) and _schema_allows_type(opt, "string") for opt in options):
                    return _coerce_value_to_string(value)

                # Fall back to first branch for recursive repair attempts.
                first_opt = next((opt for opt in options if isinstance(opt, dict)), None)
                if first_opt is not None:
                    return _repair_by_schema(value, first_opt)
                return value

        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            schema_type = next((t for t in schema_type if t != "null"), schema_type[0] if schema_type else None)

        if schema_type == "object" and isinstance(value, dict):
            props = schema.get("properties") or {}
            repaired_obj = dict(value)
            for k, child_schema in props.items():
                if k in repaired_obj and isinstance(child_schema, dict):
                    repaired_obj[k] = _repair_by_schema(repaired_obj[k], child_schema)
            return repaired_obj

        if schema_type == "array" and isinstance(value, list):
            item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else None
            if not item_schema:
                return value

            if _schema_allows_type(item_schema, "string"):
                # If schema allows strings but not objects/arrays, normalize non-string items.
                allows_object = _schema_allows_type(item_schema, "object")
                allows_array = _schema_allows_type(item_schema, "array")
                repaired_items: list[Any] = []
                for item in value:
                    if isinstance(item, str):
                        repaired_items.append(item)
                    elif (isinstance(item, dict) and allows_object) or (isinstance(item, list) and allows_array):
                        repaired_items.append(_repair_by_schema(item, item_schema))
                    else:
                        repaired_items.append(_coerce_value_to_string(item))
                return repaired_items

            return [_repair_by_schema(item, item_schema) for item in value]

        return value

    repaired = _repair_by_schema(repaired, json_schema)

    return repaired
