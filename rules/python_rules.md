# Python Rules

## Type Hints
- All public functions **must** have type hints (return type required)
- Use `from __future__ import annotations` for forward references
- Generic types: `list[str]`, `dict[str, int]`, `Optional[X]` → `X | None`

## Exception Handling
- **Never** use bare `except:` — always catch specific exception types
- Use domain exceptions from `core/exceptions.py` (ValidationError, ExecutionError, etc.)
- Re-raise with context: `raise SpecificError("message") from original_exc`
- See: [[error_handling_guidelines]]

## Async Rules
- All file I/O must be async (use `aiofiles`)
- All DB operations must be async (SQLAlchemy 2.0 async, `async_sessionmaker`)
- Never use `time.sleep()` in async contexts — use `asyncio.sleep()`

## Style
- Google docstrings: `def foo(bar: str) -> list[str]: """Does X. Args: bar: description. Returns: list of bars."""`
- Use `pathlib.Path` — never `os.path` for path operations
- Prefer `dataclasses` or Pydantic models over raw `dict` for structured data
- Imports: stdlib → third-party → local; never `from module import *`

[[error_handling_guidelines]]
