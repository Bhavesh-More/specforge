"""Ollama model management — list available models, get/set selected models via Redis."""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_redis
from src.cache.redis_client import RedisClient
from src.core.config import get_config

router = APIRouter()

REDIS_DEFAULT_MODEL_KEY = "specforge:settings:default_model"
REDIS_TEACHER_MODEL_KEY = "specforge:settings:teacher_model"

DEFAULT_MODELS = ["llama3.2", "llama3.1:8b", "llama3.1", "mistral", "codellama"]


# ─── Helpers ───────────────────────────────────────────────────────────────────


async def _fetch_ollama_models(base_url: str) -> list[str]:
    """Call Ollama /api/tags and return model names."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
        if resp.status_code != 200:
            return DEFAULT_MODELS
        data = resp.json()
        return [m["name"] for m in data.get("models", [])] or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


async def _get_model_from_redis(redis: RedisClient, key: str, default: str) -> str:
    val = await redis.get(key)
    return val if val else default


async def _set_model_in_redis(redis: RedisClient, key: str, value: str) -> None:
    await redis.set(key, value, ex=None)


# ─── Routes ────────────────────────────────────────────────────────────────────


@router.get("/models")
async def list_models() -> dict[str, Any]:
    """List all available Ollama models (from running Ollama instance)."""
    cfg = get_config()
    models = await _fetch_ollama_models(str(cfg.ollama_base_url))
    return {"models": models}


@router.get("/models/selected")
async def get_selected_models(
    redis: RedisClient = Depends(get_redis),
) -> dict[str, str]:
    """Get currently selected default and teacher model names from Redis."""
    default_model = await _get_model_from_redis(redis, REDIS_DEFAULT_MODEL_KEY, "llama3.2")
    teacher_model = await _get_model_from_redis(redis, REDIS_TEACHER_MODEL_KEY, "llama3.1:8b")
    return {
        "default_model": default_model,
        "teacher_model": teacher_model,
    }


@router.put("/models/selected")
async def update_selected_models(
    data: dict[str, str],
    redis: RedisClient = Depends(get_redis),
) -> dict[str, str]:
    """Update default and/or teacher model in Redis."""
    if "default_model" in data:
        await _set_model_in_redis(redis, REDIS_DEFAULT_MODEL_KEY, data["default_model"])
    if "teacher_model" in data:
        await _set_model_in_redis(redis, REDIS_TEACHER_MODEL_KEY, data["teacher_model"])

    default_model = await _get_model_from_redis(redis, REDIS_DEFAULT_MODEL_KEY, "llama3.2")
    teacher_model = await _get_model_from_redis(redis, REDIS_TEACHER_MODEL_KEY, "llama3.1:8b")
    return {"default_model": default_model, "teacher_model": teacher_model}


@router.get("/ollama/health")
async def ollama_health() -> dict[str, Any]:
    """Check Ollama instance health and list running models."""
    cfg = get_config()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{str(cfg.ollama_base_url).rstrip('/')}/api/tags")
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            return {"status": "healthy", "models": models}
        return {"status": "unhealthy", "models": [], "reason": f"HTTP {resp.status_code}"}
    except httpx.TimeoutException:
        return {"status": "unhealthy", "models": [], "reason": "timeout"}
    except Exception as exc:
        return {"status": "unhealthy", "models": [], "reason": str(exc)}