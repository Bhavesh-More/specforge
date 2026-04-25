"""Executions router — start, monitor, and cancel execution runs."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from fastapi.responses import FileResponse

from src.api.dependencies import get_engine, get_redis
from src.api.schemas.requests import StartExecutionRequest
from src.api.schemas.responses import ExecutionDetail, ExecutionSummary, PaginatedListResponse
from src.cache.redis_client import RedisClient 
from src.core.exceptions import TemplateNotFoundError
from src.core.logging import get_logger
from src.models.execution import ExecutionStatus, ExecutionRun
from src.reasoning.confidence_gate import SpecForgeEngine

_log = get_logger(__name__)

router = APIRouter()

RUN_INDEX_KEY = "specforge:executions:index"


def _run_key(run_id: str) -> str:
    return f"specforge:execution:{run_id}"


@router.post("/executions", response_model=ExecutionSummary, status_code=status.HTTP_202_ACCEPTED)
async def start_execution(
    req: StartExecutionRequest,
    background_tasks: BackgroundTasks,
    engine: SpecForgeEngine = Depends(get_engine),
    redis: RedisClient = Depends(get_redis),
) -> ExecutionSummary:
    """Start a new execution run (async, returns immediately with run_id)."""
    from src.compiler.template_registry import TemplateRegistry
    from pathlib import Path

    registry = TemplateRegistry(templates_dir=Path("templates"))

    try:
        template = await registry.load(req.template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    run_id = str(uuid.uuid4()) if True else req.input_data.get("run_id", str(uuid.uuid4()))
    import uuid

    run_id = str(uuid.uuid4())

    # Create a minimal ExecutionRun for tracking
    run = ExecutionRun(
        run_id=run_id,
        template_id=template.template_id,
        template_name=template.name,
        status=ExecutionStatus.PENDING,
        input_data=req.input_data,
    )

    # Store initial run in Redis
    import json
    await redis.set(_run_key(run_id), run.model_dump_json(), ex=86400)
    await redis.sadd(RUN_INDEX_KEY, run_id)

    # Background execution
    output_dir = Path(req.output_dir) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    async def _execute() -> None:
        try:
            result = await engine.execute_template(
                template=template,
                input_data=req.input_data,
                output_dir=output_dir,
                run_id=run_id,
            )
        except Exception as exc:
            _log.error("background_execution_failed", run_id=run_id, error=str(exc))
            result = ExecutionRun(
                run_id=run_id,
                template_id=template.template_id,
                template_name=template.name,
                status=ExecutionStatus.FAILED,
                error_message=str(exc),
            )
        import json
        await redis.set(_run_key(run_id), result.model_dump_json(), ex=86400)

    background_tasks.add_task(_execute)

    return ExecutionSummary(
        run_id=run_id,
        template_id=template.template_id,
        template_name=template.name,
        status=ExecutionStatus.PENDING.value,
        started_at=run.started_at,
    )


@router.get("/executions/{run_id}", response_model=ExecutionDetail)
async def get_execution(
    run_id: str,
    redis: RedisClient = Depends(get_redis),
) -> ExecutionDetail:
    """Get execution status and results."""
    import json

    raw = await redis.get(_run_key(run_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Execution run not found")

    run_dict = json.loads(raw)
    return ExecutionDetail(
        run_id=run_dict["run_id"],
        template_id=run_dict["template_id"],
        template_name=run_dict["template_name"],
        status=run_dict["status"],
        input_data=run_dict.get("input_data", {}),
        node_results=run_dict.get("node_results", {}),
        global_state=run_dict.get("global_state", {}),
        final_output=run_dict.get("final_output"),
        started_at=run_dict["started_at"],
        completed_at=run_dict.get("completed_at"),
        total_execution_time_ms=run_dict.get("total_execution_time_ms"),
        error_message=run_dict.get("error_message"),
        state_file_path=run_dict.get("state_file_path"),
    )


@router.get("/executions/{run_id}/state")
async def get_execution_state(
    run_id: str,
    redis: RedisClient = Depends(get_redis),
) -> FileResponse:
    """Return the current state.md content."""
    import json

    raw = await redis.get(_run_key(run_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Execution run not found")

    run_dict = json.loads(raw)
    state_path = run_dict.get("state_file_path")
    if not state_path:
        raise HTTPException(status_code=404, detail="state.md not yet generated")

    path = Path(state_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="state.md not found on disk")

    return FileResponse(path, media_type="text/markdown")


@router.delete("/executions/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_execution(
    run_id: str,
    redis: RedisClient = Depends(get_redis),
) -> None:
    """Cancel a running execution (marks as CANCELLED in Redis)."""
    import json

    raw = await redis.get(_run_key(run_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Execution run not found")

    run_dict = json.loads(raw)
    run_dict["status"] = ExecutionStatus.CANCELLED.value
    await redis.set(_run_key(run_id), json.dumps(run_dict), ex=86400)


@router.get("/executions", response_model=PaginatedListResponse)
async def list_executions(
    redis: RedisClient = Depends(get_redis),
) -> PaginatedListResponse:
    """List the 50 most recent execution runs."""
    import json

    run_ids = await redis.smembers(RUN_INDEX_KEY)
    recent = sorted(run_ids, reverse=True)[:50]

    runs = []
    for rid in recent:
        raw = await redis.get(_run_key(rid))
        if raw:
            d = json.loads(raw)
            runs.append(
                ExecutionSummary(
                    run_id=d["run_id"],
                    template_id=d["template_id"],
                    template_name=d["template_name"],
                    status=d["status"],
                    started_at=d["started_at"],
                    completed_at=d.get("completed_at"),
                    total_execution_time_ms=d.get("total_execution_time_ms"),
                )
            )

    return PaginatedListResponse(items=runs, total=len(runs))
