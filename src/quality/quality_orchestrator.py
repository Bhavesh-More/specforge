"""Cloud-quality orchestration: memory, teacher critique, revision, audit."""

import json
from typing import Any

from src.executor.atomic_executor import OllamaClient
from src.executor.schema_validator import SchemaValidator, extract_json_from_text
from src.healing.teacher_client import TeacherClient
from src.models.cognitive_template import CognitiveTemplate, DAGNode, NodeType
from src.quality.memory_bank import QualityMemoryBank, stable_input_hash
from src.quality.models import (
    FinalAuditResult,
    QualityConfig,
    QualityRevisionResult,
    RetrievedMemory,
    TeacherCritique,
)
from src.quality.prompts import (
    build_final_rewrite_prompt,
    build_local_revision_prompt,
    build_memory_context,
)


DEFAULT_QUALITY_DIMENSIONS = [
    "technical_depth",
    "specificity",
    "causal_trace",
    "cross_node_consistency",
    "actionability",
]


def _node_type_value(node: DAGNode) -> str:
    node_type = getattr(node, "node_type", "")
    return getattr(node_type, "value", str(node_type))


def _bento_extra(node: DAGNode, key: str) -> Any:
    bento = getattr(node, "bento_config", None)
    if bento is None:
        return None
    direct = getattr(bento, key, None)
    if direct is not None:
        return direct
    extra = getattr(bento, "model_extra", None) or {}
    return extra.get(key)


def _is_deep_reason(node: DAGNode) -> bool:
    return node.node_type == NodeType.DEEP_REASON or _node_type_value(node) == "deep_reason"


def _safe_json_loads(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        extracted = extract_json_from_text(text)
        if extracted:
            try:
                parsed = json.loads(extracted)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
    return None


class QualityOrchestrator:
    """Coordinates memory retrieval, teacher critique, revision, and final audit."""

    def __init__(
        self,
        *,
        memory_bank: QualityMemoryBank,
        teacher_client: TeacherClient | None,
        local_client: OllamaClient,
        schema_validator: SchemaValidator,
    ) -> None:
        self.memory_bank = memory_bank
        self.teacher_client = teacher_client
        self.local_client = local_client
        self.schema_validator = schema_validator

    async def prepare_node_context(
        self,
        *,
        template: CognitiveTemplate,
        node: DAGNode,
        run_id: str,
        input_data: dict[str, Any],
        global_state: dict[str, Any],
        quality_config: QualityConfig,
    ) -> tuple[dict[str, Any], list[RetrievedMemory], str]:
        """Retrieve memories and return augmented global state plus context text."""
        del run_id
        if not quality_config.use_memory:
            return dict(global_state), [], ""

        task_text = self._task_text(node=node, input_data=input_data, global_state=global_state)
        memories = await self.memory_bank.retrieve(
            template_id=template.template_id,
            task_text=task_text,
            node_id=node.node_id,
            node_type=_node_type_value(node),
            limit=5,
        )
        memory_context = build_memory_context(memories)
        augmented_state = dict(global_state)
        if memory_context:
            augmented_state["__quality_memory_context__"] = memory_context
        return augmented_state, memories, memory_context

    async def maybe_improve_node_output(
        self,
        *,
        template: CognitiveTemplate,
        node: DAGNode,
        run_id: str,
        input_data: dict[str, Any],
        global_state: dict[str, Any],
        raw_output: str,
        parsed_output: dict[str, Any] | None,
        memory_context: str,
        quality_config: QualityConfig,
    ) -> QualityRevisionResult:
        """Optionally teacher-critique and locally revise a successful node output."""
        del run_id
        original = QualityRevisionResult(
            used_revision=False,
            original_output=raw_output,
            revised_output=None,
            critique=None,
            quality_score=None,
            reason="quality revision disabled",
        )
        if (
            quality_config.mode != "cloud"
            or not quality_config.teacher_on_success
            or quality_config.max_revision_rounds <= 0
            or self.teacher_client is None
            or not self._is_important_node(node, quality_config)
        ):
            return original

        task_text = self._task_text(node=node, input_data=input_data, global_state=global_state)
        cloud_quality = _bento_extra(node, "cloud_quality") or {}
        quality_dimensions = cloud_quality.get("quality_dimensions") or DEFAULT_QUALITY_DIMENSIONS

        critique = await self.teacher_client.critique_successful_output(
            template_name=template.name,
            node=node,
            original_task=task_text,
            current_output=raw_output,
            output_schema={} if _is_deep_reason(node) else node.focus_prompt.output_schema,
            quality_dimensions=quality_dimensions,
            memory_context=memory_context,
        )

        min_score = float(cloud_quality.get("min_quality_score") or quality_config.min_quality_score)
        if not critique.should_revise and critique.quality_score >= min_score:
            return QualityRevisionResult(
                used_revision=False,
                original_output=raw_output,
                critique=critique,
                quality_score=critique.quality_score,
                reason="teacher accepted original output",
            )

        revised_raw = await self.local_client.generate(
            system_prompt=(
                "You are a careful local specialist model revising your own output "
                "according to teacher feedback."
            ),
            user_message=build_local_revision_prompt(
                original_task=task_text,
                original_output=raw_output,
                teacher_critique=critique,
                output_schema={} if _is_deep_reason(node) else node.focus_prompt.output_schema,
                memory_context=memory_context,
            ),
            max_tokens=max(node.focus_prompt.max_tokens, 1200),
            json_mode=bool(node.focus_prompt.output_schema) and not _is_deep_reason(node),
        )

        if _is_deep_reason(node):
            if revised_raw.strip() and len(revised_raw.strip()) >= max(80, int(len(raw_output) * 0.8)):
                return QualityRevisionResult(
                    used_revision=True,
                    original_output=raw_output,
                    revised_output=revised_raw,
                    critique=critique,
                    quality_score=critique.quality_score,
                    reason="accepted revised deep reasoning prose",
                )
            return QualityRevisionResult(
                used_revision=False,
                original_output=raw_output,
                revised_output=revised_raw,
                critique=critique,
                quality_score=critique.quality_score,
                reason="revised deep reasoning was empty or too short",
            )

        validation = self.schema_validator.validate_output(
            revised_raw, node.focus_prompt.output_schema
        )
        if validation.is_valid:
            return QualityRevisionResult(
                used_revision=True,
                original_output=raw_output,
                revised_output=revised_raw,
                critique=critique,
                quality_score=critique.quality_score,
                reason="accepted validated teacher-guided revision",
            )

        return QualityRevisionResult(
            used_revision=False,
            original_output=raw_output,
            revised_output=revised_raw,
            critique=critique,
            quality_score=critique.quality_score,
            reason="revised output failed schema validation; kept original",
        )

    async def record_node_result(
        self,
        *,
        template: CognitiveTemplate,
        node: DAGNode,
        run_id: str,
        input_data: dict[str, Any],
        global_state: dict[str, Any],
        raw_output: str,
        parsed_output: dict[str, Any] | None,
        status: str,
        quality_result: QualityRevisionResult | None = None,
    ) -> None:
        """Persist node outcome and critique memory."""
        task_text = self._task_text(node=node, input_data=input_data, global_state=global_state)
        input_hash = stable_input_hash(input_data)
        quality_score = quality_result.quality_score if quality_result else None

        if status.startswith("passed"):
            await self.memory_bank.record_node_success(
                template_id=template.template_id,
                template_name=template.name,
                run_id=run_id,
                node_id=node.node_id,
                node_type=_node_type_value(node),
                task_text=task_text,
                input_hash=input_hash,
                parsed_output=parsed_output,
                raw_output=raw_output,
                quality_score=quality_score,
            )
        else:
            await self.memory_bank.record_node_failure(
                template_id=template.template_id,
                template_name=template.name,
                run_id=run_id,
                node_id=node.node_id,
                node_type=_node_type_value(node),
                task_text=task_text,
                input_hash=input_hash,
                raw_output=raw_output,
                error=status,
            )

        if quality_result and quality_result.critique:
            await self.memory_bank.record_teacher_critique(
                template_id=template.template_id,
                template_name=template.name,
                run_id=run_id,
                node_id=node.node_id,
                node_type=_node_type_value(node),
                task_text=task_text,
                input_hash=input_hash,
                critique=quality_result.critique.model_dump(),
                quality_score=quality_result.critique.quality_score,
            )

    async def audit_and_polish_final_output(
        self,
        *,
        template: CognitiveTemplate,
        run_id: str,
        input_data: dict[str, Any],
        final_output: dict[str, Any],
        quality_config: QualityConfig,
    ) -> FinalAuditResult:
        """Run final teacher audit and optional local rewrite."""
        memory_context = ""
        if quality_config.use_memory:
            memories = await self.memory_bank.retrieve(
                template_id=template.template_id,
                task_text=json.dumps(input_data, sort_keys=True, default=str),
                limit=5,
            )
            memory_context = build_memory_context(memories)

        if not quality_config.final_audit or self.teacher_client is None:
            output = self._with_quality_meta(final_output, quality_config, None, [])
            await self._record_final(template, run_id, input_data, output, None)
            return FinalAuditResult(
                audited_output=output,
                used_audit_rewrite=False,
                audit_notes=[],
                quality_score=None,
            )

        audit = await self.teacher_client.audit_final_output(
            template_name=template.name,
            user_input=input_data,
            final_output=final_output,
            memory_context=memory_context,
        )
        quality_score = _coerce_float(audit.get("quality_score"))
        audit_notes_raw = audit.get("audit_notes") or []
        consistency_raw = audit.get("consistency_issues") or []
        missing_raw = audit.get("missing_details") or []
        instructions_raw = audit.get("rewrite_instructions") or []
        audit_unavailable = "Teacher final audit unavailable" in audit_notes_raw
        audit_is_empty = not any(
            [audit_notes_raw, consistency_raw, missing_raw, instructions_raw]
        )
        should_rewrite = (not audit_unavailable) and (
            bool(audit.get("should_rewrite")) or (
            quality_score is not None and quality_score < quality_config.min_quality_score
            )
        )
        if audit_is_empty:
            should_rewrite = False
        notes = list(audit_notes_raw)
        notes.extend(str(item) for item in consistency_raw)

        if not should_rewrite:
            output = self._with_quality_meta(final_output, quality_config, quality_score, notes)
            output["_quality_audit"] = audit
            await self._record_final(template, run_id, input_data, output, quality_score)
            return FinalAuditResult(
                audited_output=output,
                used_audit_rewrite=False,
                audit_notes=notes,
                quality_score=quality_score,
            )

        rewritten_raw = await self.local_client.generate(
            system_prompt="You are a careful final editor for SpecForge JSON outputs.",
            user_message=build_final_rewrite_prompt(
                user_input=input_data,
                final_output=final_output,
                audit=audit,
            ),
            max_tokens=4096,
            json_mode=True,
        )
        rewritten = _safe_json_loads(rewritten_raw)
        if rewritten is None:
            output = self._with_quality_meta(final_output, quality_config, quality_score, notes)
            output["_quality_audit"] = audit
            await self._record_final(template, run_id, input_data, output, quality_score)
            return FinalAuditResult(
                audited_output=output,
                used_audit_rewrite=False,
                audit_notes=notes + ["final rewrite was not valid JSON"],
                quality_score=quality_score,
            )

        if not _preserves_final_output_detail(final_output, rewritten):
            output = self._with_quality_meta(final_output, quality_config, quality_score, notes)
            output["_quality_audit"] = {
                **audit,
                "rewrite_rejected": True,
                "rewrite_rejection_reason": (
                    "final rewrite removed existing fields or substantially reduced detail"
                ),
            }
            await self._record_final(template, run_id, input_data, output, quality_score)
            return FinalAuditResult(
                audited_output=output,
                used_audit_rewrite=False,
                audit_notes=notes + ["final rewrite rejected because it lost detail"],
                quality_score=quality_score,
            )

        if "_specforge_meta" in final_output:
            rewritten["_specforge_meta"] = final_output["_specforge_meta"]
        rewritten = self._with_quality_meta(rewritten, quality_config, quality_score, notes)
        rewritten["_quality_audit"] = audit
        await self._record_final(template, run_id, input_data, rewritten, quality_score)
        return FinalAuditResult(
            audited_output=rewritten,
            used_audit_rewrite=True,
            audit_notes=notes,
            quality_score=quality_score,
        )

    def _is_important_node(self, node: DAGNode, quality_config: QualityConfig) -> bool:
        cloud_quality = _bento_extra(node, "cloud_quality") or {}
        if cloud_quality.get("enabled") is True:
            return True
        return (
            node.node_id in quality_config.important_node_ids
            or _node_type_value(node) in quality_config.important_node_types
        )

    def _task_text(
        self,
        *,
        node: DAGNode,
        input_data: dict[str, Any],
        global_state: dict[str, Any],
    ) -> str:
        state_keys = ", ".join(sorted(global_state.keys()))
        return (
            f"Node: {node.node_id}\n"
            f"Purpose: {node.description}\n"
            f"Template prompt: {node.focus_prompt.user_template[:1500]}\n"
            f"Input: {json.dumps(input_data, sort_keys=True, default=str)[:3000]}\n"
            f"Available prior state keys: {state_keys}"
        )

    def _with_quality_meta(
        self,
        output: dict[str, Any],
        quality_config: QualityConfig,
        final_quality_score: float | None,
        audit_notes: list[str],
    ) -> dict[str, Any]:
        enriched = dict(output)
        enriched["_quality_meta"] = {
            "mode": quality_config.mode,
            "memory_used": quality_config.use_memory,
            "teacher_on_success": quality_config.teacher_on_success,
            "final_audit": quality_config.final_audit,
            "final_quality_score": final_quality_score,
            "audit_note_count": len(audit_notes),
        }
        return enriched

    async def _record_final(
        self,
        template: CognitiveTemplate,
        run_id: str,
        input_data: dict[str, Any],
        final_output: dict[str, Any],
        quality_score: float | None,
    ) -> None:
        task_text = json.dumps(input_data, sort_keys=True, default=str)
        await self.memory_bank.record_final_output(
            template_id=template.template_id,
            template_name=template.name,
            run_id=run_id,
            task_text=task_text,
            input_hash=stable_input_hash(input_data),
            final_output=final_output,
            quality_score=quality_score,
        )


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _preserves_final_output_detail(
    original: dict[str, Any],
    rewritten: dict[str, Any],
) -> bool:
    """Reject final rewrites that make a rich result shallow.

    Final audit is allowed to polish, but it must not discard user-visible
    sections, remove list items, or collapse long analysis into tiny snippets.
    """
    ignored = {"_quality_meta", "_quality_audit"}
    for key, original_value in original.items():
        if key in ignored:
            continue
        if key not in rewritten:
            return False
        if not _value_preserves_detail(original_value, rewritten[key]):
            return False
    return True


def _value_preserves_detail(original: Any, rewritten: Any) -> bool:
    if isinstance(original, dict):
        if not isinstance(rewritten, dict):
            return False
        for key, value in original.items():
            if key not in rewritten:
                return False
            if not _value_preserves_detail(value, rewritten[key]):
                return False
        return True

    if isinstance(original, list):
        if not isinstance(rewritten, list):
            return False
        if len(rewritten) < len(original):
            return False
        for original_item, rewritten_item in zip(original, rewritten):
            if not _value_preserves_detail(original_item, rewritten_item):
                return False
        return True

    if isinstance(original, str):
        if not isinstance(rewritten, str):
            return False
        original_text = original.strip()
        rewritten_text = rewritten.strip()
        if len(original_text) >= 160 and len(rewritten_text) < int(len(original_text) * 0.65):
            return False
        if original_text and not rewritten_text:
            return False
    return True
