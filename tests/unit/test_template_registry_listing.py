import asyncio

from src.compiler.template_registry import TemplateRegistry


def test_list_templates_includes_named_ct_json_files(tmp_path):
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    (templates_dir / "bug_report.ct.json").write_text(
        """
{
  "template_id": "11111111-1111-1111-1111-111111111111",
  "name": "Bug Report Analysis",
  "version": "1.0.0",
  "description": "Default template",
  "tags": ["default"]
}
""".strip(),
        encoding="utf-8",
    )

    registry = TemplateRegistry(templates_dir=templates_dir)
    templates = asyncio.run(registry.list_templates())

    assert len(templates) == 1
    assert templates[0]["name"] == "Bug Report Analysis"
    assert templates[0]["version"] == "1.0.0"