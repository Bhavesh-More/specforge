"""FastAPI dependency injection — session factories, clients, singletons."""

from pathlib import Path
from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache.redis_client import RedisClient , get_redis_client
from src.compiler.template_registry import TemplateRegistry
from src.core.config import get_config
from src.db.database import async_session_factory
from src.executor.atomic_executor import OllamaClient, create_ollama_client
from src.knowledge.graph_manager import KnowledgeGraphManager
from src.reasoning.confidence_gate import SpecForgeEngine
from src.symbolic.mcp_client import MCPClient
from src.symbolic.symbolic_node import SymbolicNodeExecutor
from src.symbolic.tool_registry import ToolRegistry
from src.executor.atomic_executor import AtomicExecutor
from src.executor.context_surgeon import ContextSurgeon
from src.executor.schema_validator import RetryOrchestrator, SchemaValidator
from src.healing.failure_detector import FailureTracker
from src.healing.teacher_client import TeacherClient
from src.healing.rule_patcher import RulePatcher
from src.healing import SelfHealingOrchestrator
from src.reasoning.adversarial_triad import AdversarialTriad
from src.reasoning.lookahead_dag import LookaheadDAG
from src.executor.result_weaver import ResultWeaver, StateFileWriter
from src.quality.memory_bank import QualityMemoryBank
from src.quality.quality_orchestrator import QualityOrchestrator
from specforge.memory import MemoryAdapter, MemoryRetriever, MemoryStore

# ─── Database session ──────────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Per-request async database session (yielded, auto-closed)."""
    async with async_session_factory() as session:
        yield session


# ─── Redis client ──────────────────────────────────────────────────────────────


_redis_client: RedisClient | None = None


async def get_redis() -> RedisClient:
    """Return the app-level Redis client singleton."""
    global _redis_client
    if _redis_client is None:
        cfg = get_config()
        _redis_client = RedisClient(redis_url=str(cfg.redis_url))
        await _redis_client.connect()
    return _redis_client


# ─── Ollama client ──────────────────────────────────────────────────────────────


async def get_ollama_client() -> OllamaClient:
    """Return the app-level Ollama client singleton."""
    cfg = get_config()
    return create_ollama_client(base_url=str(cfg.ollama_base_url), model="llama3.2")


async def get_selected_model(redis: RedisClient = Depends(get_redis)) -> str:
    """Return the currently selected default model from Redis."""
    val = await redis.get("specforge:settings:default_model")
    return val if val else "llama3.2"


async def get_teacher_model(redis: RedisClient = Depends(get_redis)) -> str:
    """Return the currently selected teacher model from Redis."""
    val = await redis.get("specforge:settings:teacher_model")
    return val if val else "llama3.1:8b"


# ─── Tool registry + MCP client ──────────────────────────────────────────────────


async def get_tool_registry() -> ToolRegistry:
    """Return a ToolRegistry singleton."""
    return ToolRegistry()


async def get_mcp_client(
    registry: ToolRegistry = Depends(get_tool_registry),
) -> MCPClient:
    """Return an MCPClient singleton."""
    return MCPClient(registry=registry)


# ─── Execution engine components ────────────────────────────────────────────────


async def get_context_surgeon() -> ContextSurgeon:
    """Return a ContextSurgeon for the rules directory."""
    project_root = Path(__file__).parent.parent.parent
    rules_dir = project_root / "rules"
    return ContextSurgeon(rules_dir=rules_dir)


async def get_atomic_executor(
    ollama: OllamaClient = Depends(get_ollama_client),
    surgeon: ContextSurgeon = Depends(get_context_surgeon),
    selected_model: str = Depends(get_selected_model),
) -> AtomicExecutor:
    """Return an AtomicExecutor instance."""
    ollama.model = selected_model
    return AtomicExecutor(ollama_client=ollama, context_surgeon=surgeon)


async def get_schema_validator() -> SchemaValidator:
    """Return a SchemaValidator singleton."""
    return SchemaValidator()


async def get_retry_orchestrator(
    executor: AtomicExecutor = Depends(get_atomic_executor),
    validator: SchemaValidator = Depends(get_schema_validator),
) -> RetryOrchestrator:
    """Return a RetryOrchestrator instance."""
    return RetryOrchestrator(atomic_executor=executor, schema_validator=validator)


async def get_failure_tracker() -> FailureTracker:
    """Return a FailureTracker singleton."""
    return FailureTracker()


async def get_healing_orchestrator(
    tracker: FailureTracker = Depends(get_failure_tracker),
    mcp: MCPClient = Depends(get_mcp_client),
    selected_model: str = Depends(get_selected_model),
    teacher_model: str = Depends(get_teacher_model),
) -> SelfHealingOrchestrator:
    """Return a SelfHealingOrchestrator instance."""
    cfg = get_config()
    project_root = Path(__file__).parent.parent.parent
    rules_dir = project_root / "rules"
    ollama = create_ollama_client(base_url=str(cfg.ollama_base_url), model=selected_model)
    teacher = TeacherClient(ollama_client=ollama, model=teacher_model)
    patcher = RulePatcher(rules_dir=rules_dir)
    return SelfHealingOrchestrator(
        tracker=tracker,
        teacher=teacher,
        patcher=patcher,
        rules_dir=rules_dir,
    )


async def get_adversarial_triad(
    executor: AtomicExecutor = Depends(get_atomic_executor),
    validator: SchemaValidator = Depends(get_schema_validator),
) -> AdversarialTriad:
    """Return an AdversarialTriad instance."""
    return AdversarialTriad(atomic_executor=executor, schema_validator=validator)


async def get_lookahead_dag(
    executor: AtomicExecutor = Depends(get_atomic_executor),
    validator: SchemaValidator = Depends(get_schema_validator),
) -> LookaheadDAG:
    """Return a LookaheadDAG instance."""
    return LookaheadDAG(atomic_executor=executor, schema_validator=validator)


async def get_symbolic_executor(
    mcp: MCPClient = Depends(get_mcp_client),
    executor: AtomicExecutor = Depends(get_atomic_executor),
) -> SymbolicNodeExecutor:
    """Return a SymbolicNodeExecutor instance."""
    return SymbolicNodeExecutor(mcp_client=mcp, atomic_executor=executor)


# ─── Template registry ─────────────────────────────────────────────────────────


async def get_template_registry() -> TemplateRegistry:
    """Return a TemplateRegistry singleton for the templates directory."""
    # Resolve templates directory relative to project root (parent of src/)
    project_root = Path(__file__).parent.parent.parent
    templates_dir = project_root / "templates"
    return TemplateRegistry(templates_dir=templates_dir)


# ─── Knowledge graph manager ────────────────────────────────────────────────────


async def get_knowledge_manager() -> KnowledgeGraphManager:
    """Return the app-level KnowledgeGraphManager singleton from app state."""
    return KnowledgeGraphManager(rules_dir=Path("rules"))


# ─── SpecForge engine ────────────────────────────────────────────────────────────


async def get_confidence_gate(
    retry: RetryOrchestrator = Depends(get_retry_orchestrator),
    triad: AdversarialTriad = Depends(get_adversarial_triad),
    lookahead: LookaheadDAG = Depends(get_lookahead_dag),
    symbolic: SymbolicNodeExecutor = Depends(get_symbolic_executor),
    tracker: FailureTracker = Depends(get_failure_tracker),
    healing: SelfHealingOrchestrator = Depends(get_healing_orchestrator),
) -> "ConfidenceGate":
    """Return a ConfidenceGate instance."""
    from src.reasoning.confidence_gate import ConfidenceGate
    return ConfidenceGate(
        retry_orchestrator=retry,
        adversarial_triad=triad,
        lookahead_dag=lookahead,
        symbolic_executor=symbolic,
        failure_tracker=tracker,
        healing_orchestrator=healing,
    )


async def get_state_writer() -> StateFileWriter:
    """Return a StateFileWriter (path set at execution time)."""
    return StateFileWriter(state_file_path=Path(""))


async def get_result_weaver(
    state_writer: StateFileWriter = Depends(get_state_writer),
) -> ResultWeaver:
    """Return a ResultWeaver instance."""
    return ResultWeaver(state_writer=state_writer)


async def get_quality_memory_bank() -> QualityMemoryBank:
    """Return the local quality memory bank."""
    project_root = Path(__file__).parent.parent.parent
    db_path = project_root / "output" / "quality_memory.sqlite3"
    bank = QualityMemoryBank(db_path=db_path)
    await bank.initialize()
    return bank


async def get_failure_memory_store() -> MemoryStore:
    """Return the proactive Failure Memory Bank store."""
    project_root = Path(__file__).parent.parent.parent
    output_dir = project_root / "output"
    return MemoryStore(
        db_path=str(output_dir / "failure_memory.sqlite3"),
        chroma_path=str(output_dir / "failure_chroma"),
    )


async def get_quality_orchestrator(
    memory_bank: QualityMemoryBank = Depends(get_quality_memory_bank),
    failure_memory_store: MemoryStore = Depends(get_failure_memory_store),
    selected_model: str = Depends(get_selected_model),
    teacher_model: str = Depends(get_teacher_model),
) -> QualityOrchestrator:
    """Return the cloud-quality orchestrator."""
    cfg = get_config()
    local = create_ollama_client(
        base_url=str(cfg.ollama_base_url),
        model=selected_model,
    )
    teacher_base = create_ollama_client(
        base_url=str(cfg.ollama_base_url),
        model=selected_model,
    )
    teacher = TeacherClient(ollama_client=teacher_base, model=teacher_model)
    return QualityOrchestrator(
        memory_bank=memory_bank,
        teacher_client=teacher,
        local_client=local,
        schema_validator=SchemaValidator(),
        failure_memory_store=failure_memory_store,
        failure_memory_adapter=MemoryAdapter(MemoryRetriever(failure_memory_store)),
    )


async def get_engine(
    gate: "ConfidenceGate" = Depends(get_confidence_gate),
    weaver: ResultWeaver = Depends(get_result_weaver),
    state_writer: StateFileWriter = Depends(get_state_writer),
    registry: TemplateRegistry = Depends(get_template_registry),
    kg: KnowledgeGraphManager = Depends(get_knowledge_manager),
    quality: QualityOrchestrator = Depends(get_quality_orchestrator),
) -> SpecForgeEngine:
    """Return a SpecForgeEngine singleton."""
    return SpecForgeEngine(
        confidence_gate=gate,
        result_weaver=weaver,
        state_writer=state_writer,
        template_registry=registry,
        knowledge_manager=kg,
        quality_orchestrator=quality,
    )
