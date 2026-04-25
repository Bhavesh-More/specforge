"""FastAPI application factory for SpecForge API."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.config import get_config
from src.core.exceptions import SpecForgeError
from src.core.logging import get_logger
from src.db.database import AsyncEngine, async_session_factory
from src.knowledge.graph_manager import KnowledgeGraphManager
from src.executor.atomic_executor import OllamaClient, create_ollama_client

_log = get_logger(__name__)

# ─── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    On startup:
    - Check Ollama health
    - Initialize database (create tables if needed)
    - Initialize knowledge graph index
    """
    cfg = get_config()

    # Check Ollama health
    ollama_client = create_ollama_client(cfg)
    ollama_healthy = await ollama_client.health_check()
    if not ollama_healthy:
        _log.warning("ollama_health_check_failed", url=str(cfg.ollama_base_url))
    else:
        _log.info("ollama_health_check_passed", url=str(cfg.ollama_base_url))

    # Initialize database (async engine)
    try:
        from src.db.database import init_db
        await init_db(str(cfg.database_url))
        app.state.db_available = True
        _log.info("db_initialized")
    except Exception as e:
        app.state.db_available = False
        _log.warning("db_unavailable", error=str(e))

    # Initialize knowledge graph
    rules_dir = Path("rules")
    rules_dir.mkdir(parents=True, exist_ok=True)
    kg = KnowledgeGraphManager(rules_dir=rules_dir)
    await kg.initialize()

    # Store on app state
    app.state.ollama = ollama_client
    app.state.knowledge_manager = kg

    _log.info("specforge_api_startup_complete")
    yield

    # Shutdown
    await ollama_client.close()
    _log.info("specforge_api_shutdown_complete")


# ─── App factory ────────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    cfg = get_config()

    app = FastAPI(
        title="SpecForge API",
        description="Offline-first reasoning orchestration framework",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware — allow all in dev, restrict in prod
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if cfg.debug else ["https://specforge.io"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler for domain errors
    @app.exception_handler(SpecForgeError)
    async def specforge_error_handler(request: Request, exc: SpecForgeError) -> JSONResponse:
        _log.error(
            "specforge_domain_error",
            code=exc.code,
            message=exc.message,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "context": exc.context,
                }
            },
        )

    # Register routers
    from src.api.routers import executions, healing, knowledge, templates

    app.include_router(templates.router, prefix="/api/v1", tags=["templates"])
    app.include_router(executions.router, prefix="/api/v1", tags=["executions"])
    app.include_router(knowledge.router, prefix="/api/v1", tags=["knowledge"])
    app.include_router(healing.router, prefix="/api/v1", tags=["healing"])

    return app
