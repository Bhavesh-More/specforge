"""Async SQLAlchemy database engine and session factory."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_config

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the cached async engine singleton."""
    global _engine
    if _engine is None:
        cfg = get_config()
        _engine = create_async_engine(
            str(cfg.database_url),
            echo=cfg.debug,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
    return _engine


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the cached async session factory singleton."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncSession:
    """Per-request async session (for FastAPI Depends)."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db() -> None:
    """Create all tables defined by SQLAlchemy models.

    Called on application startup to verify connectivity and create schema.
    """
    from src.db.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose the engine — called on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
