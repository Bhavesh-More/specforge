"""Ollama router — health check, available model listing, and model config."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from src.api.schemas.requests import to_camel
from src.cache.redis_client import get_redis_client
from src.core.config import get_config
from src.executor.atomic_executor import create_ollama_client

router = APIRouter()

REDIS_KEY_MAIN = "specforge:ollama:main_model"
REDIS_KEY_TEACHER = "specforge:ollama:teacher_model"


class OllamaHealthResponse(BaseModel):
    status: str
    url: str
    model: str | None


class OllamaModel(BaseModel):
    name: str
    size: int | None = None
    modified_at: str | None = None


class OllamaModelsResponse(BaseModel):
    models: list[OllamaModel]
    count: int


class OllamaConfigResponse(BaseModel):
    """Response for model config. Uses camelCase alias so frontend receives mainModel/teacherModel."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    main_model: str
    teacher_model: str


class OllamaConfigRequest(BaseModel):
    """Request to persist model configuration. Accepts camelCase from frontend."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    main_model: str
    teacher_model: str


@router.get("/ollama/health", response_model=OllamaHealthResponse)
async def ollama_health() -> OllamaHealthResponse:
    """Check Ollama connectivity and current model."""
    cfg = get_config()
    client = create_ollama_client(cfg)
    try:
        healthy = await client.health_check()
        if healthy:
            return OllamaHealthResponse(
                status="healthy",
                url=str(cfg.ollama_base_url),
                model=cfg.ollama_model,
            )
        else:
            return OllamaHealthResponse(
                status="unhealthy",
                url=str(cfg.ollama_base_url),
                model=None,
            )
    finally:
        await client.close()


@router.get("/ollama/models", response_model=OllamaModelsResponse)
async def list_ollama_models() -> OllamaModelsResponse:
    """List all locally available Ollama models."""
    cfg = get_config()
    client = create_ollama_client(cfg)
    try:
        tags = await client.list_local_models()
        return OllamaModelsResponse(
            models=[
                OllamaModel(
                    name=m["name"],
                    size=m.get("size"),
                    modified_at=m.get("modified_at"),
                )
                for m in tags
            ],
            count=len(tags),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list models: {exc}")
    finally:
        await client.close()


@router.get("/ollama/config", response_model=OllamaConfigResponse)
async def get_ollama_config() -> OllamaConfigResponse:
    """Get the configured main and teacher models.

    Reads from Redis if previously set, otherwise falls back to environment/config defaults.
    """
    redis = await get_redis_client()
    cfg = get_config()
    main = await redis.get(REDIS_KEY_MAIN)
    teacher = await redis.get(REDIS_KEY_TEACHER)
    return OllamaConfigResponse(
        main_model=main or cfg.ollama_model,
        teacher_model=teacher or cfg.ollama_teacher_model,
    )


@router.put("/ollama/config", response_model=OllamaConfigResponse)
async def update_ollama_config(req: OllamaConfigRequest) -> OllamaConfigResponse:
    """Persist main and teacher model selection to Redis."""
    redis = await get_redis_client()
    await redis.set(REDIS_KEY_MAIN, req.main_model)
    await redis.set(REDIS_KEY_TEACHER, req.teacher_model)
    return OllamaConfigResponse(
        main_model=req.main_model,
        teacher_model=req.teacher_model,
    )