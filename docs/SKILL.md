---
name: generate-template
description: Generate a SpecForge Cognitive Template (.ct.json) from a natural language task description. Use this skill whenever the user says "generate-template", mentions creating a .ct.json file, wants to build a DAG workflow, describes a multi-step automated process, or asks to create a Cognitive Template for any task. Trigger even for casual phrasing like "make me a template for X" or "I want to automate a pipeline that does Y". Always use this skill when the user describes a workflow with multiple steps or processing nodes.
---

# Generate Cognitive Template

Generate a complete Cognitive Template in `.ct.json` format from a natural language task description.

## Purpose

Convert user-described workflows into valid SpecForge `.ct.json` DAGs, with properly typed nodes, configured focus prompts, and correct dependency chains.

## Processing Steps

1. **Analyze task description** — Identify actions, data transformations, and decision points
2. **Determine nodes** — One node per major step; extract parallelizable branches
3. **Assign node types** — See type guide below
4. **Define dependencies** — `depends_on` references prior node IDs; no circular deps
5. **Configure prompts** — System prompt defines role; `user_template` references upstream outputs via `{{node_id.field}}` or `{{input_var}}`
6. **Set parameters** — Temperature/tokens tuned to task determinism
7. **Validate** — All `depends_on` IDs must exist; all `required_variables` must be reachable
8. **Output** — Emit only the JSON, wrapped in a `json` code block, with filename comment on top

## Node Type Guide

| Type | When to Use |
|------|-------------|
| `standard` | General text processing, analysis, transformations |
| `symbolic` | Tool execution, calculations, API calls |
| `adversarial` | Validation, quality checks, error detection |
| `lookahead` | Planning steps, anticipating outcomes |
| `parallel` | Independent tasks that can run concurrently |

## Output Rules

- Output **only** valid JSON in a code block — no prose before or after
- `template_id`: `kebab-case-task-YYYYMMDD` using today's date
- Node IDs: short, lowercase, snake_case, meaningful (e.g. `extractor`, `classifier`)
- `output_key`: always `"output"` unless node produces a named field
- `can_run_parallel`: `true` for nodes with no shared upstream writes
- `max_retries`: 2–3 for standard; 1 for adversarial
- `temperature`: 0.2–0.4 for classification/extraction; 0.6–0.8 for generation/creative
- `output_schema`: flat key→type map (no nested objects)
- `created_at` / `updated_at`: use current timestamp in ISO 8601
- `schema_version`: `1.0.0`

## Template Skeleton

```json
{
  "template_id": "task-name-YYYYMMDD",
  "name": "Human Readable Name",
  "description": "One sentence description",
  "version": "1.0.0",
  "schema_version": "1.0.0",
  "nodes": [
    {
      "node_id": "node_id",
      "name": "Node Name",
      "description": "What this node does",
      "node_type": "standard|symbolic|adversarial|lookahead|parallel",
      "focus_prompt": {
        "system_prompt": "You are a ...",
        "user_template": "Process: {{input_variable}}",
        "output_schema": {
          "field_name": "string|number|boolean"
        },
        "required_variables": ["input_variable"],
        "max_tokens": 500,
        "temperature": 0.3
      },
      "depends_on": [],
      "can_run_parallel": true,
      "max_retries": 2,
      "symbolic_tool": null,
      "output_key": "output"
    }
  ],
  "created_at": "ISO-8601-timestamp",
  "updated_at": "ISO-8601-timestamp",
  "tags": ["generated", "task-category"],
  "author": "claude-skill"
}
```

## Example

**Input:** `generate-template: Summarize news articles — fetch URL, extract key facts, score credibility, write summary`

**Output:**
```json
// news-summarizer-20260515.ct.json
{
  "template_id": "news-summarizer-20260515",
  "name": "News Article Summarizer",
  "description": "Fetch a news article, extract facts, score credibility, and produce a summary",
  "version": "1.0.0",
  "schema_version": "1.0.0",
  "nodes": [
    {
      "node_id": "fetcher",
      "name": "Article Fetcher",
      "description": "Retrieve raw article text from a URL",
      "node_type": "symbolic",
      "focus_prompt": {
        "system_prompt": "You are a web content retrieval assistant. Extract the main body text of a news article from its URL.",
        "user_template": "Fetch article from: {{url}}",
        "output_schema": { "raw_text": "string", "title": "string", "source": "string" },
        "required_variables": ["url"],
        "max_tokens": 1000,
        "temperature": 0.2
      },
      "depends_on": [],
      "can_run_parallel": true,
      "max_retries": 3,
      "symbolic_tool": "web_fetch",
      "output_key": "output"
    },
    {
      "node_id": "fact_extractor",
      "name": "Fact Extractor",
      "description": "Pull key facts, people, dates, and claims from the article",
      "node_type": "standard",
      "focus_prompt": {
        "system_prompt": "You are a journalism analyst. Extract verifiable facts, named entities, dates, and primary claims.",
        "user_template": "Extract facts from: {{fetcher.raw_text}}",
        "output_schema": { "facts": "string", "entities": "string", "claims": "string" },
        "required_variables": ["fetcher"],
        "max_tokens": 800,
        "temperature": 0.3
      },
      "depends_on": ["fetcher"],
      "can_run_parallel": true,
      "max_retries": 2,
      "symbolic_tool": null,
      "output_key": "output"
    },
    {
      "node_id": "credibility_scorer",
      "name": "Credibility Scorer",
      "description": "Evaluate source reliability and claim credibility",
      "node_type": "adversarial",
      "focus_prompt": {
        "system_prompt": "You are a fact-checking assistant. Score the credibility of the source and its claims on a 0–10 scale.",
        "user_template": "Source: {{fetcher.source}} | Claims: {{fact_extractor.claims}}",
        "output_schema": { "score": "number", "reasoning": "string" },
        "required_variables": ["fetcher", "fact_extractor"],
        "max_tokens": 300,
        "temperature": 0.4
      },
      "depends_on": ["fetcher", "fact_extractor"],
      "can_run_parallel": false,
      "max_retries": 1,
      "symbolic_tool": null,
      "output_key": "output"
    },
    {
      "node_id": "summarizer",
      "name": "Summary Writer",
      "description": "Write a concise, neutral summary of the article",
      "node_type": "standard",
      "focus_prompt": {
        "system_prompt": "You are a professional editor. Write a clear, neutral 3-paragraph summary.",
        "user_template": "Title: {{fetcher.title}}\nFacts: {{fact_extractor.facts}}\nCredibility score: {{credibility_scorer.score}}\nWrite a summary.",
        "output_schema": { "summary": "string" },
        "required_variables": ["fetcher", "fact_extractor", "credibility_scorer"],
        "max_tokens": 600,
        "temperature": 0.6
      },
      "depends_on": ["fact_extractor", "credibility_scorer"],
      "can_run_parallel": false,
      "max_retries": 2,
      "symbolic_tool": null,
      "output_key": "output"
    }
  ],
  "created_at": "2026-05-15T00:00:00Z",
  "updated_at": "2026-05-15T00:00:00Z",
  "tags": ["generated", "news", "summarization"],
  "author": "claude-skill"
}
```

## Edge Cases

- **Single-step task** → still wrap in one node; don't skip the template format
- **Ambiguous dependencies** → prefer adding a dependency (safe) over missing one (breaks DAG)
- **Branching outputs** → use `parallel` node_type; set `can_run_parallel: true` on sibling nodes
- **Tool-calling nodes** → set `node_type: "symbolic"` and fill `symbolic_tool` with the tool name
- **No input variables named** → use `input` as the default top-level variable name