from pathlib import Path
from typing import Any

import pytest

from src.executor.schema_validator import SchemaValidator
from src.models.cognitive_template import CognitiveTemplate, DAGNode
from src.quality.memory_bank import QualityMemoryBank
from src.quality.models import QualityConfig, TeacherCritique
from src.quality.quality_orchestrator import QualityOrchestrator


class FakeLocalClient:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    async def generate(self, **kwargs: Any) -> str:
        self.calls += 1
        return self.response


class FakeTeacher:
    def __init__(
        self,
        critique: TeacherCritique | None = None,
        audit: dict[str, Any] | None = None,
    ):
        self.critique = critique or TeacherCritique(
            quality_score=0.3,
            should_revise=True,
            improvement_instructions=["add specificity"],
        )
        self.audit = audit or {
            "quality_score": 0.9,
            "audit_notes": ["ok"],
            "consistency_issues": [],
            "missing_details": [],
            "rewrite_instructions": [],
            "should_rewrite": False,
        }
        self.critique_calls = 0

    async def critique_successful_output(self, **kwargs: Any) -> TeacherCritique:
        self.critique_calls += 1
        return self.critique

    async def audit_final_output(self, **kwargs: Any) -> dict[str, Any]:
        return self.audit


def make_node() -> DAGNode:
    return DAGNode(
        node_id="root_cause",
        name="Root Cause",
        node_type="standard",
        description="Structure root cause",
        focus_prompt={
            "system_prompt": "Return JSON.",
            "user_template": "Return JSON.",
            "output_schema": {
                "type": "object",
                "required": ["root_cause"],
                "properties": {"root_cause": {"type": "string"}},
            },
        },
        bento_config={
            "cloud_quality": {
                "enabled": True,
                "teacher_review": True,
                "quality_dimensions": ["specificity"],
            }
        },
        output_key="root_cause",
    )


def make_template() -> CognitiveTemplate:
    return CognitiveTemplate(
        template_id="bug_report",
        name="Bug Report",
        quality_config={"mode": "cloud", "important_node_ids": ["root_cause"]},
        nodes=[make_node()],
    )


async def make_orchestrator(
    tmp_path: Path,
    local_response: str,
    teacher: FakeTeacher | None = None,
) -> QualityOrchestrator:
    bank = QualityMemoryBank(tmp_path / "quality.sqlite3")
    await bank.initialize()
    return QualityOrchestrator(
        memory_bank=bank,
        teacher_client=teacher or FakeTeacher(),
        local_client=FakeLocalClient(local_response),
        schema_validator=SchemaValidator(),
    )


@pytest.mark.asyncio
async def test_standard_mode_does_not_call_teacher(tmp_path: Path):
    teacher = FakeTeacher()
    orchestrator = await make_orchestrator(
        tmp_path, '{"root_cause": "improved"}', teacher=teacher
    )

    result = await orchestrator.maybe_improve_node_output(
        template=make_template(),
        node=make_node(),
        run_id="run",
        input_data={"description": "bug"},
        global_state={},
        raw_output='{"root_cause": "original"}',
        parsed_output={"root_cause": "original"},
        memory_context="",
        quality_config=QualityConfig(mode="standard"),
    )

    assert result.used_revision is False
    assert teacher.critique_calls == 0


@pytest.mark.asyncio
async def test_cloud_mode_valid_revision_replaces_original(tmp_path: Path):
    orchestrator = await make_orchestrator(tmp_path, '{"root_cause": "improved"}')

    result = await orchestrator.maybe_improve_node_output(
        template=make_template(),
        node=make_node(),
        run_id="run",
        input_data={"description": "bug"},
        global_state={},
        raw_output='{"root_cause": "original"}',
        parsed_output={"root_cause": "original"},
        memory_context="",
        quality_config=QualityConfig(mode="cloud", important_node_ids=["root_cause"]),
    )

    assert result.used_revision is True
    assert result.revised_output == '{"root_cause": "improved"}'


@pytest.mark.asyncio
async def test_cloud_mode_invalid_revision_falls_back(tmp_path: Path):
    orchestrator = await make_orchestrator(tmp_path, '{"root_cause": 123}')

    result = await orchestrator.maybe_improve_node_output(
        template=make_template(),
        node=make_node(),
        run_id="run",
        input_data={"description": "bug"},
        global_state={},
        raw_output='{"root_cause": "original"}',
        parsed_output={"root_cause": "original"},
        memory_context="",
        quality_config=QualityConfig(mode="cloud", important_node_ids=["root_cause"]),
    )

    assert result.used_revision is False
    assert "failed schema" in result.reason


@pytest.mark.asyncio
async def test_final_audit_preserves_specforge_meta(tmp_path: Path):
    teacher = FakeTeacher(
        audit={
            "quality_score": 0.2,
            "audit_notes": ["rewrite"],
            "consistency_issues": [],
            "missing_details": [],
            "rewrite_instructions": ["tighten"],
            "should_rewrite": True,
        }
    )
    orchestrator = await make_orchestrator(
        tmp_path,
        '{"answer": "rewritten", "_specforge_meta": {"run_id": "wrong"}}',
        teacher=teacher,
    )

    result = await orchestrator.audit_and_polish_final_output(
        template=make_template(),
        run_id="run",
        input_data={"description": "bug"},
        final_output={"answer": "old", "_specforge_meta": {"run_id": "right"}},
        quality_config=QualityConfig(mode="cloud"),
    )

    assert result.used_audit_rewrite is True
    assert result.audited_output["_specforge_meta"] == {"run_id": "right"}
