from pathlib import Path

from src.cli.main import _load_template


def test_load_template_accepts_filesystem_path(tmp_path, monkeypatch):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    template_file = template_dir / "bug_report.ct.json"
    template_file.write_text(
        """
{
  "template_id": "11111111-1111-1111-1111-111111111111",
  "name": "Bug Report Analysis",
  "description": "Analyzes bug reports and generates fix plans",
  "version": "1.0.0",
  "schema_version": "1.0.0",
  "nodes": [
    {
      "node_id": "parse",
      "name": "Parse",
      "description": "Parse the bug report",
      "node_type": "standard",
      "focus_prompt": {
        "system_prompt": "Parse bug reports.",
        "user_template": "Parse: {report}",
        "output_schema": {},
        "required_variables": [],
        "max_tokens": 256,
        "temperature": 0.3
      },
      "bento_config": {
        "rule_files": [],
        "follow_links": false,
        "max_depth": 0,
        "token_budget": 256
      },
      "depends_on": [],
      "can_run_parallel": false,
      "max_retries": 3,
      "symbolic_tool": null,
      "output_key": "parsed_bug"
    }
  ],
  "created_at": "2026-04-25T00:00:00+00:00",
  "updated_at": "2026-04-25T00:00:00+00:00",
  "tags": [],
  "author": "anonymous"
}
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    template = _load_template("templates/bug_report.ct.json")

    assert template.name == "Bug Report Analysis"
    assert template.nodes[0].node_id == "parse"