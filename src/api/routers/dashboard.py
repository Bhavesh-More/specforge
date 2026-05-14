"""Dashboard router — stats and recent executions."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_redis
from src.cache.redis_client import RedisClient
from src.compiler.template_registry import TemplateRegistry
from src.core.logging import get_logger
import asyncio

_log = get_logger(__name__)

router = APIRouter()


@router.get("/stats")
async def get_stats(
    redis: RedisClient = Depends(get_redis),
) -> dict:
    """Get aggregate statistics for the dashboard."""
    # Resolve paths relative to project root (parent of src/)
    project_root = Path(__file__).parent.parent.parent.parent
    templates_dir = project_root / "templates"

    # Count templates
    template_registry = TemplateRegistry(templates_dir=templates_dir)
    templates = await template_registry.list_templates()
    templates_count = len(templates)

    # Count healing events from Redis (actual healing events, not .md files)
    healing_events_count = 0
    try:
        healing_keys = await redis.smembers("specforge:healing_events:index")
        healing_events_count = len(healing_keys)
    except Exception as e:
        _log.warning("redis_healing_warning", error=str(e))

    # Count registry templates (if any)
    registry_templates = 0

    # Get execution count from Redis (handle connection errors gracefully)
    executions_count = 0
    try:
        run_ids = await redis.smembers("specforge:executions:index")
        executions_count = len(run_ids)
    except Exception as e:
        _log.warning("redis_connection_warning", error=str(e))

    return {
        "templates_count": templates_count,
        "executions_count": executions_count,
        "healing_events_count": healing_events_count,
        "registry_templates": registry_templates,
    }


@router.get("/executions/recent")
async def get_recent_executions(
    limit: int = 5,
    redis: RedisClient = Depends(get_redis),
) -> list:
    """Get the most recent execution runs."""
    RUN_INDEX_KEY = "specforge:executions:index"

    try:
        run_ids = await redis.smembers(RUN_INDEX_KEY)
        if not run_ids:
            return []
    except Exception as e:
        _log.warning("redis_connection_warning", error=str(e))
        return []

    # Get most recent run_ids (sorted by ID which is UUID)
    recent_ids = sorted(run_ids, reverse=True)[:limit]

    runs = []
    for rid in recent_ids:
        try:
            raw = await redis.get(f"specforge:execution:{rid}")
            if raw:
                d = json.loads(raw)
                runs.append(
                    {
                        "runId": d["run_id"],
                        "templateId": d["template_id"],
                        "templateName": d["template_name"],
                        "status": d["status"],
                        "inputData": d.get("input_data", {}),
                        "finalOutput": d.get("final_output"),
                        "errorMessage": d.get("error_message"),
                        "startedAt": d["started_at"],
                        "completedAt": d.get("completed_at"),
                        "totalExecutionTimeMs": d.get("total_execution_time_ms"),
                        "stateFilePath": d.get("state_file_path"),
                        "nodeResults": d.get("node_results", {}),
                    }
                )
        except Exception as e:
            _log.warning("redis_get_warning", run_id=rid, error=str(e))

    return runs
