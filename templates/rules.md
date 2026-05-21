# SpecForge Template Rules

Use this file as the contract for authoring and maintaining `.ct.json` templates in SpecForge.

## Top-Level Fields

Every template should include:
- `template_id`: stable unique identifier
- `name`: human-readable template name
- `description`: one-paragraph summary of what the template does
- `version`: semver string like `1.0.0`
- `schema_version`: the SpecForge template schema version
- `nodes`: ordered list of DAG nodes
- `created_at`: ISO-8601 timestamp
- `updated_at`: ISO-8601 timestamp
- `tags`: array of filter tags
- `author`: template author or generator

## Node Fields

Every node should include:
- `node_id`: unique lowercase identifier
- `name`: display label for the node
- `description`: short explanation of the node’s role
- `node_type`: one of `standard`, `deep_reason`, `adversarial`, `parallel`, `lookahead`, `symbolic`
- `focus_prompt`: prompt object for the model
- `bento_config`: context and reasoning configuration
- `depends_on`: list of upstream `node_id` values
- `can_run_parallel`: boolean
- `max_retries`: integer retry limit
- `symbolic_tool`: required only for `symbolic` nodes
- `output_key`: key used to store node output in global state

## Focus Prompt Fields

Every `focus_prompt` should include:
- `system_prompt`: model role and behavior
- `user_template`: the actual prompt with `{variables}`
- `output_schema`: JSON Schema for validation
- `required_variables`: variables that must exist before execution
- `max_tokens`: token cap for the node
- `temperature`: sampling temperature

## Field Behavior

- Use `description` as the most common top-level intake field when the template should accept one bundled input object or text blob.
- Use `required_variables` only for values the runtime must resolve before execution.
- Use `unknown` only when the template explicitly allows uncertainty.
- Do not invent custom fields unless the backend schema supports them.
- Keep field names aligned with SpecForge backend models exactly.

## Validation Rules

- Template JSON must load through `CognitiveTemplate.load_from_file()`.
- Node IDs must be unique.
- `depends_on` values must refer to real nodes.
- `symbolic` nodes must declare `symbolic_tool`.
- `output_schema` should describe the exact shape expected from the model.
- If a node is input-sensitive, prefer a single bundled `description` field over many fragile top-level variables.

## Recommended Authoring Pattern

1. Start with a bundled `description` input unless the template truly needs separate variables.
2. Parse that input into a normalized evidence or metadata object.
3. Keep early nodes tolerant of uncertainty.
4. Put strict validation in downstream nodes.
5. Use final validation or finalize nodes to enforce the final contract.

## Data Exfiltration Template Notes

For incident-response templates, the first node should:
- accept one bundled description input
- parse JSON if present
- preserve severity if present
- fall back to `unknown` only when necessary
- normalize the rest of the evidence for later nodes
