# Error Handling Guidelines

## Core Rules

**1. Always log exceptions with full context before raising.**
```python
log.error("节点执行失败", extra={"node_id": node_id, "run_id": run_id, "error": str(exc)})
raise ExecutionError(f"Node {node_id} failed after {attempt} attempts") from exc
```

**2. Use specific exception types — never bare `raise Exception()`.**

Domain exceptions (defined in `core/exceptions.py`):
- `ValidationError` — schema/contract violations
- `ExecutionError` — node execution failures
- `HealingError` — self-healing loop failures
- `GraphError` — knowledge graph errors
- `CompilerError` — template/DAG compilation errors

**3. Re-raise with context using `raise X from Y`.**
```python
try:
    await session.execute(query)
except DBConnectionError as exc:
    raise ExecutionError("Database connection failed during node execution") from exc
```

**4. Never swallow exceptions silently.**
```python
# BAD
try:
    do_something()
except SomeError:
    pass

# GOOD
try:
    do_something()
except SomeError as exc:
    log.warning("Optional recovery action taken", error=str(exc))
    raise
```

## Error Response Format (API Layer)
```json
{
    "error": "ErrorName",
    "message": "Human-readable description",
    "details": {}
}
```

API layer converts exceptions to HTTP responses via `dependencies.py`.
