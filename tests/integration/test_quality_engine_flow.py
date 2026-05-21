from pathlib import Path
from typing import Any

import pytest

from src.executor.result_weaver import ResultWeaver, StateFileWriter
from src.executor.schema_validator import SchemaValidator
from src.models.cognitive_template import CognitiveTemplate
from src.models.execution import NodeResult, NodeStatus, ValidationResult
from src.models.cognitive_template import ExecutionTier
from src.quality.memory_bank import QualityMemoryBank
from src.quality.models import TeacherCritique
from src.quality.quality_orchestrator import QualityOrchestrator
from src.reasoning.confidence_gate import SpecForgeEngine


class FakeGate:
    async def execute_node(self, **kwargs: Any) -> NodeResult:
        node = kwargs["node"]
        raw = '{"root_cause": "original shallow cause"}'
        parsed = {"root_cause": "original shallow cause"}
        return NodeResult(
            node_id=node.node_id,
            status=NodeStatus.PASSED_TIER1,
            tier_used=ExecutionTier.FAST,
            raw_output=raw,
            parsed_output=parsed,
            validation_result=ValidationResult(
                is_valid=True,
                raw_output=raw,
                parsed_output=parsed,
            ),
            attempt_count=1,
        )


class FakeKnowledgeManager:
    async def initialize(self) -> None:
        return None


class FakeLocalClient:
    async def generate(self, **kwargs: Any) -> str:
        if kwargs.get("json_mode"):
            if "Rewrite the final SpecForge output" in kwargs["user_message"]:
                return '{"root_cause": {"root_cause": "final polished cause"}}'
            return '{"root_cause": "revised deeper causal explanation"}'
        return "revised prose"


class FakeTeacher:
    async def critique_successful_output(self, **kwargs: Any) -> TeacherCritique:
        return TeacherCritique(
            quality_score=0.2,
            should_revise=True,
            improvement_instructions=["add causal detail"],
        )

    async def audit_final_output(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "quality_score": 0.9,
            "audit_notes": ["consistent"],
            "consistency_issues": [],
            "missing_details": [],
            "rewrite_instructions": [],
            "should_rewrite": False,
        }


@pytest.mark.asyncio
async def test_engine_quality_flow_adds_revision_memory_and_meta(tmp_path: Path):
    template = CognitiveTemplate(
        template_id="bug_report",
        name="Bug Report",
        quality_config={
            "mode": "cloud",
            "important_node_ids": ["root_cause"],
            "final_audit": True,
        },
        nodes=[
            {
                "node_id": "root_cause",
                "name": "Root Cause",
                "node_type": "standard",
                "description": "Find root cause",
                "focus_prompt": {
                    "system_prompt": "Return JSON.",
                    "user_template": "Analyze {description}",
                    "required_variables": ["description"],
                    "output_schema": {
                        "type": "object",
                        "required": ["root_cause"],
                        "properties": {"root_cause": {"type": "string"}},
                    },
                },
                "bento_config": {
                    "cloud_quality": {
                        "enabled": True,
                        "teacher_review": True,
                    }
                },
                "output_key": "root_cause",
            }
        ],
    )
    state_writer = StateFileWriter(tmp_path / "state.md")
    memory_bank = QualityMemoryBank(tmp_path / "quality.sqlite3")
    await memory_bank.initialize()
    quality = QualityOrchestrator(
        memory_bank=memory_bank,
        teacher_client=FakeTeacher(),
        local_client=FakeLocalClient(),
        schema_validator=SchemaValidator(),
    )
    engine = SpecForgeEngine(
        confidence_gate=FakeGate(),
        result_weaver=ResultWeaver(state_writer),
        state_writer=state_writer,
        template_registry=None,
        knowledge_manager=FakeKnowledgeManager(),
        quality_orchestrator=quality,
    )

    run = await engine.execute_template(
        template=template,
        input_data={"description": "websocket reconnect corruption"},
        output_dir=tmp_path / "run",
        run_id="run-1",
    )

    assert run.final_output is not None
    assert run.final_output["root_cause"]["root_cause"] == "revised deeper causal explanation"
    assert run.final_output["_quality_meta"]["mode"] == "cloud"

    memories = await memory_bank.retrieve(
        template_id="bug_report",
        task_text="websocket reconnect corruption",
        node_id="root_cause",
        node_type="standard",
    )
    assert memories
