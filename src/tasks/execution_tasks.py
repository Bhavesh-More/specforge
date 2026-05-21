"""Celery execution tasks for SpecForge background template execution."""

import asyncio
import json
from pathlib import Path

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from src.cache.redis_client import RedisClient 
from src.core.config import get_config
from src.core.exceptions import SpecForgeError
from src.core.logging import get_logger
from src.executor.atomic_executor import AtomicExecutor, OllamaClient, create_ollama_client
from src.executor.context_surgeon import ContextSurgeon
from src.executor.result_weaver import ResultWeaver, StateFileWriter
from src.executor.schema_validator import RetryOrchestrator, SchemaValidator
from src.compiler.template_registry import TemplateRegistry
from src.knowledge.graph_manager import KnowledgeGraphManager
from src.models.execution import ExecutionRun, ExecutionStatus
from src.reasoning.adversarial_triad import AdversarialTriad
from src.reasoning.confidence_gate import ConfidenceGate, SpecForgeEngine
from src.reasoning.lookahead_dag import LookaheadDAG
from src.healing.failure_detector import FailureTracker
from src.healing.teacher_client import TeacherClient
from src.healing.rule_patcher import RulePatcher
from src.healing import SelfHealingOrchestrator
from src.quality.memory_bank import QualityMemoryBank
from src.quality.quality_orchestrator import QualityOrchestrator
from src.symbolic.mcp_client import MCPClient
from src.symbolic.symbolic_node import SymbolicNodeExecutor
from src.symbolic.tool_registry import ToolRegistry
from src.tasks.celery_app import celery_app

_log = get_logger(__name__)

# ─── Redis event publisher ──────────────────────────────────────────────────────


async def _publish_run_event(run_id: str, event: dict) -> None:
    """Publish a run status event to Redis pubsub channel.

    Args:
        run_id: The execution run ID.
        event: Event dict to publish.
    """
    cfg = get_config()
    redis = RedisClient(redis_url=str(cfg.redis_url))
    await redis.connect()
    channel = f"specforge:run:{run_id}:events"
    await redis.publish(channel, json.dumps(event))
    await redis.close()


# ─── Dependency injection for tasks ──────────────────────────────────────────


def _build_engine() -> SpecForgeEngine:
    """Build a fully-wired SpecForgeEngine for use inside a Celery task.

    Constructs all dependencies synchronously since Celery tasks are sync.
    """
    cfg = get_config()
    rules_dir = Path("rules")
    templates_dir = Path("templates")

    # Tool registry + MCP
    tool_registry = ToolRegistry()
    mcp_client = MCPClient(registry=tool_registry)

    # Ollama
    default_model = getattr(cfg, "ollama_model", "llama3.1:8b")
    teacher_model = getattr(cfg, "ollama_teacher_model", "llama3.1:8b")
    ollama = create_ollama_client(
        base_url=str(cfg.ollama_base_url),
        model=default_model,
        temperature=cfg.ollama_temperature,
    )

    # Context surgeon
    surgeon = ContextSurgeon(rules_dir=rules_dir)

    # Atomic executor
    atomic_executor = AtomicExecutor(ollama_client=ollama, context_surgeon=surgeon)

    # Schema validator + retry orchestrator
    validator = SchemaValidator()
    retry_orchestrator = RetryOrchestrator(
        atomic_executor=atomic_executor,
        schema_validator=validator,
    )

    # Adversarial triad + lookahead
    triad = AdversarialTriad(atomic_executor=atomic_executor, schema_validator=validator)
    lookahead = LookaheadDAG(atomic_executor=atomic_executor, schema_validator=validator)

    # Symbolic executor
    symbolic_executor = SymbolicNodeExecutor(mcp_client=mcp_client, atomic_executor=atomic_executor)

    # Healing
    tracker = FailureTracker()
    teacher = TeacherClient(
        ollama_client=create_ollama_client(
            base_url=str(cfg.ollama_base_url),
            model=default_model,
            temperature=cfg.ollama_temperature,
        ),
        model=teacher_model,
    )
    patcher = RulePatcher(rules_dir=rules_dir)
    healing = SelfHealingOrchestrator(
        tracker=tracker,
        teacher=teacher,
        patcher=patcher,
        rules_dir=rules_dir,
    )

    # Confidence gate
    gate = ConfidenceGate(
        retry_orchestrator=retry_orchestrator,
        adversarial_triad=triad,
        lookahead_dag=lookahead,
        symbolic_executor=symbolic_executor,
        failure_tracker=tracker,
        healing_orchestrator=healing,
    )

    # State writer + result weaver
    state_writer = StateFileWriter(state_file_path=Path(""))
    weaver = ResultWeaver(state_writer=state_writer)

    # Registry + knowledge manager
    registry = TemplateRegistry(templates_dir=templates_dir)
    kg = KnowledgeGraphManager(rules_dir=rules_dir)
    memory_bank = QualityMemoryBank(db_path=Path("output") / "quality_memory.sqlite3")
    # The memory bank lazily initializes again during first use in the web path,
    # but Celery builds synchronously, so create the table here.
    memory_bank._initialize_sync()
    quality = QualityOrchestrator(
        memory_bank=memory_bank,
        teacher_client=teacher,
        local_client=ollama,
        schema_validator=validator,
    )

    return SpecForgeEngine(
        confidence_gate=gate,
        result_weaver=weaver,
        state_writer=state_writer,
        template_registry=registry,
        knowledge_manager=kg,
        quality_orchestrator=quality,
    )


# ─── Celery tasks ──────────────────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="specforge.execute_template",
    max_retries=0,
    acks_late=True,
)
def run_template_execution(
    self: Task,
    run_id: str,
    template_id: str,
    input_data: dict,
    output_dir: str,
) -> dict:
    """Execute a cognitive template as a background Celery task.

    Args:
        self: Celery task binder (provides self.request).
        run_id: Unique execution run ID.
        template_id: ID of the template to execute.
        input_data: Input payload dict.
        output_dir: Directory path for state.md and outputs.

    Returns:
        Dict with run_id and status ("completed" | "failed").
    """
    cfg = get_config()
    templates_dir = Path("templates")
    output_path = Path(output_dir) / run_id
    output_path.mkdir(parents=True, exist_ok=True)

    async def _async_execute() -> dict:
        registry = TemplateRegistry(templates_dir=templates_dir)
        engine = _build_engine()

        # Load template
        try:
            template = await registry.load(template_id)
        except SpecForgeError as exc:
            _log.error("task_template_load_failed", run_id=run_id, error=str(exc))
            return {"run_id": run_id, "status": "failed", "error": str(exc)}

        # Set state file path on the engine's state writer
        engine._state._path = output_path / "state.md"

        try:
            result = await engine.execute_template(
                template=template,
                input_data=input_data,
                output_dir=output_path,
                run_id=run_id,
            )
            status = "completed" if result.status == ExecutionStatus.COMPLETED else "failed"

            # Store result in Redis
            redis = RedisClient(redis_url=str(cfg.redis_url))
            await redis.connect()
            run_key = f"specforge:run:{run_id}"
            await redis.set(run_key, result.model_dump_json(), ex=86400)
            await redis.close()

            return {
                "run_id": run_id,
                "status": status,
                "state_file_path": str(output_path / "state.md"),
            }

        except Exception as exc:
            _log.error("task_execution_failed", run_id=run_id, error=str(exc))

            # Store failed run in Redis
            redis = RedisClient(redis_url=str(cfg.redis_url))
            await redis.connect()
            failed_run = ExecutionRun(
                run_id=run_id,
                template_id=template_id,
                template_name="",
                status=ExecutionStatus.FAILED,
                error_message=str(exc),
            )
            await redis.set(f"specforge:run:{run_id}", failed_run.model_dump_json(), ex=86400)
            await redis.close()

            return {"run_id": run_id, "status": "failed", "error": str(exc)}

    # Run the async co-routine inside the sync Celery task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_async_execute())
    finally:
        loop.close()

    return result


@celery_app.task(name="specforge.cleanup_expired_runs")
def cleanup_expired_runs() -> dict:
    """Periodic Celery Beat task to clean up expired execution runs from Redis."""
    _log.info("cleanup_expired_runs_task_started")

    async def _async_cleanup() -> dict:
        cfg = get_config()
        redis = RedisClient(redis_url=str(cfg.redis_url))
        await redis.connect()

        index_key = "specforge:executions:index"
        run_ids = await redis.smembers(index_key)

        deleted = 0
        for run_id in run_ids:
            key = f"specforge:run:{run_id}"
            if not await redis.exists(key):
                # Run has expired — remove from index
                await redis.delete(key)
                deleted += 1

        await redis.close()
        return {"deleted": deleted, "checked": len(run_ids)}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_async_cleanup())
    finally:
        loop.close()

    return result
