from src.models.cognitive_template import CognitiveTemplate
from src.quality.models import QualityConfig


def test_old_template_gets_default_quality_config():
    template = CognitiveTemplate(
        template_id="simple",
        name="Simple",
        nodes=[
            {
                "node_id": "a",
                "name": "A",
                "node_type": "standard",
                "focus_prompt": {
                    "system_prompt": "Return JSON.",
                    "user_template": "Return {\"ok\": true}",
                    "output_schema": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                    },
                },
                "output_key": "a",
            }
        ],
    )

    assert template.quality_config.mode == "standard"
    assert template.quality_config.teacher_on_success is False


def test_cloud_mode_normalizes_quality_switches():
    cfg = QualityConfig(mode="cloud", max_revision_rounds=0)

    assert cfg.use_memory is True
    assert cfg.teacher_on_success is True
    assert cfg.final_audit is True
    assert cfg.max_revision_rounds == 1


def test_standard_mode_disables_teacher_on_success():
    cfg = QualityConfig(
        mode="standard",
        teacher_on_success=True,
        final_audit=True,
        max_revision_rounds=2,
    )

    assert cfg.teacher_on_success is False
    assert cfg.final_audit is False
    assert cfg.max_revision_rounds == 0
