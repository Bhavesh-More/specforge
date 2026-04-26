# Error Handling Guidelines

Standards for handling and reporting errors in SpecForge.

## Always Log Exceptions with Context

When catching an exception, log it with enough context to reconstruct what happened.

```python
_log.error(
    "node_execution_failed",
    node_id=node.node_id,
    template_id=self.template_id,
    attempt=attempt_number,
    error=str(exc),
    exc_info=True,
)
```

Never log `exc_info=False` (the default) when the exception is the error — without the traceback, debugging is significantly harder.

## Use Specific Exception Types

Define domain-specific exceptions in `src/core/exceptions.py`. Never raise bare `Exception` or `RuntimeError`.

```python
# Correct
raise NodeExecutionError(
    node_id=node.node_id,
    attempt_count=attempt_number,
    last_output=raw_output,
    context={"error": str(exc)},
)

# Wrong
raise Exception(f"Node {node.node_id} failed")
```

## Re-raise with Context

When transforming a low-level exception into a domain exception, use `raise X from Y`:

```python
try:
    parsed = json.loads(raw_output)
except json.JSONDecodeError as exc:
    raise SchemaValidationError(
        f"Node output not valid JSON: {exc.msg}"
    ) from exc
```

`from exc` preserves the original traceback in the exception chain — critical for tracing back to the root cause in logs.

## Exception Hierarchy

All custom exceptions inherit from `SpecForgeError` (defined in `src/core/exceptions.py`). This allows callers to catch all project-specific errors with a single `except SpecForgeError:`.

```python
class SpecForgeError(Exception):
    """Base exception for all SpecForge errors."""
    code: str = "SPECFORGE_ERROR"
    context: dict | None = None

class TemplateNotFoundError(SpecForgeError):
    code = "TEMPLATE_NOT_FOUND"
```

## What Not to Do

- **Don't swallow exceptions** with empty `except:` blocks — errors disappear silently and become impossible to debug.
- **Don't discard the original exception** when wrapping — always use `from original_exc`.
- **Don't raise generic types** (`Exception`, `ValueError`, `TypeError`) from library code — define project-specific types instead.
- **Don't log and re-raise** without the log line — otherwise the error reappears in logs without the context you captured.
