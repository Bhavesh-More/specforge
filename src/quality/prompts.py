"""Prompt builders for cloud-quality critique and revision."""

import json
from typing import Any

from src.quality.models import RetrievedMemory, TeacherCritique


def _short(value: Any, max_chars: int = 700) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:max_chars]


def build_memory_context(memories: list[RetrievedMemory], max_chars: int = 1800) -> str:
    """Return compact prompt text summarizing previous relevant memories."""
    if not memories:
        return ""

    lines = ["## Relevant SpecForge Memory"]
    for memory in memories:
        record = memory.record
        label = {
            "success": "Previous success",
            "failure": "Previous failure to avoid",
            "teacher_critique": "Teacher advice",
            "final_output": "Prior final output",
            "domain_insight": "Domain insight",
        }.get(record.record_type, record.record_type)
        lines.append(
            f"- {label} ({memory.similarity:.2f}, {memory.reason}): "
            f"{_short(record.content, 500)}"
        )
    lines.append("Use these as guidance. Do not copy blindly.")
    text = "\n".join(lines)
    return text[:max_chars]


def build_teacher_critique_prompt(
    *,
    template_name: str,
    node_id: str,
    node_description: str,
    node_type: str,
    original_task: str,
    current_output: str,
    output_schema: dict[str, Any],
    quality_dimensions: list[str],
    memory_context: str,
) -> str:
    """Build a teacher prompt for scoring a successful local output."""
    return f"""You are reviewing a successful local-model output for SpecForge.

Template: {template_name}
Node ID: {node_id}
Node type: {node_type}
Node purpose: {node_description}
Quality dimensions: {", ".join(quality_dimensions)}

{memory_context}

Original task:
{original_task}

Current output:
{current_output}

Output schema:
{json.dumps(output_schema, indent=2, ensure_ascii=False)}

Score the output like a strict cloud-model evaluator. Look for missing depth,
unsupported claims, generic advice, contradictions with memory or task, and
places where the output failed to preserve earlier deep reasoning.

Output ONLY valid JSON:
{{
  "quality_score": 0.0,
  "missing_details": [],
  "unsupported_claims": [],
  "consistency_issues": [],
  "improvement_instructions": [],
  "should_revise": true,
  "concise_summary": "short critique summary"
}}"""


def build_local_revision_prompt(
    *,
    original_task: str,
    original_output: str,
    teacher_critique: TeacherCritique,
    output_schema: dict[str, Any],
    memory_context: str,
) -> str:
    """Build prompt for the local model to revise its own output."""
    schema_text = json.dumps(output_schema, indent=2, ensure_ascii=False)
    critique_text = teacher_critique.model_dump_json(indent=2)
    json_instruction = (
        "Output ONLY valid JSON matching the schema exactly."
        if output_schema
        else "Output detailed prose. Do not wrap it in JSON."
    )
    return f"""Revise your previous output using the teacher critique.

{memory_context}

Original task:
{original_task}

Your previous output:
{original_output}

Teacher critique:
{critique_text}

Required output schema:
{schema_text}

Rules:
- Preserve the original schema exactly.
- Fix only the issues identified by the teacher.
- Add missing technical depth, specificity, and causal reasoning.
- Do not invent facts not grounded in the input, memory, or reasoning.
- Keep correct details from the previous output.
- {json_instruction}
"""


def build_final_audit_prompt(
    *,
    template_name: str,
    user_input: dict[str, Any],
    final_output: dict[str, Any],
    memory_context: str,
) -> str:
    """Build teacher prompt for final cross-node audit."""
    return f"""You are auditing the final output of a SpecForge template run.

Template: {template_name}

{memory_context}

User input:
{json.dumps(user_input, indent=2, ensure_ascii=False, default=str)}

Final output:
{json.dumps(final_output, indent=2, ensure_ascii=False, default=str)}

Check cross-node consistency:
- severity must match root cause and risks
- proposed fixes must address identified root causes
- executive summary must not invent effort estimates or new facts
- important fields should not be "unknown" when evidence exists
- output must remain grounded in the user input
- output should be useful to a real engineering/business user

Output ONLY valid JSON:
{{
  "quality_score": 0.0,
  "audit_notes": [],
  "consistency_issues": [],
  "missing_details": [],
  "rewrite_instructions": [],
  "should_rewrite": true
}}"""


def build_final_rewrite_prompt(
    *,
    user_input: dict[str, Any],
    final_output: dict[str, Any],
    audit: dict[str, Any],
) -> str:
    """Build local final rewrite prompt."""
    return f"""Rewrite the final SpecForge output according to the audit.

User input:
{json.dumps(user_input, indent=2, ensure_ascii=False, default=str)}

Current final output:
{json.dumps(final_output, indent=2, ensure_ascii=False, default=str)}

Audit:
{json.dumps(audit, indent=2, ensure_ascii=False, default=str)}

Rules:
- Preserve the same top-level structure and all useful fields.
- Preserve _specforge_meta exactly if present.
- Do not invent facts, estimates, or file names.
- Fix contradictions and shallow/generic sections.
- The summary field, if present, must remain valid for its existing shape.
- Output ONLY one valid JSON object.
"""
