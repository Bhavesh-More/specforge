# Python Rules

Standards for Python code in this project. Follow these when writing or reviewing Python code.

## Type Hints

All function signatures must have type hints on parameters and return values.

```python
# Good
def process_items(items: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    ...

# Bad
def process_items(items, limit=None):
    ...
```

Generic types from `typing` for anything that isn't a built-in: `list[T]`, `dict[K, V]`, `set[T]`, `Optional[T]`, `Union[A, B]`.

## Exception Handling

### Specific Exception Types

Catch and raise specific exception types. Never catch bare `Exception` or `BaseException`.

```python
# Good
except ValueError as exc:
    raise ProcessingError(f"Invalid input: {exc}") from exc

# Bad
except Exception:
    pass
```

### No Bare Except

Every `except` block must specify an exception type. Empty except blocks are prohibited.

```python
# Good
except FileNotFoundError:
    return None

# Bad
except:
    pass
```

### Re-raising with Context

When re-raising an exception after wrapping it, use `raise X from Y` to preserve the traceback chain.

```python
try:
    result = parse_config(raw)
except TomlDecodeError as exc:
    raise ConfigurationError(f"Config parse failed: {exc}") from exc
```

See [[error_handling_guidelines]] for full context on exception handling patterns.

## Async Rules

- Use `async def` for all functions that perform I/O.
- Never use `requests` library — use `httpx` with `AsyncClient`.
- Never call `asyncio.run()` inside an already-async context — use `await` directly or `asyncio.create_task()`.

## Imports

- Standard library imports first, then third-party, then project modules.
- Use absolute imports: `from src.cache.redis_client import RedisClient` not `from ..cache.redis_client import ...`.
