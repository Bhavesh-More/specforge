# Code Review Standards

## PR Requirements
- Every new module requires a corresponding `tests/unit/test_X.py`
- All public functions need type hints and Google docstrings
- No bare `except:` — always catch specific exceptions
- Pydantic models must use v2 `model_config = ConfigDict(...)` syntax

## Review Checklist
- [ ] Tests pass (`pytest`)
- [ ] Type hints present and correct
- [ ] No synchronous file I/O in async contexts
- [ ] Redis keys use `specforge:` namespace
- [ ] SQLAlchemy uses async `AsyncSession`, not sync session
- [ ] Environment variables via `pydantic_settings.BaseSettings`
- [ ] API responses use snake_case internally, camelCase via alias_generator
