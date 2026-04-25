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
    return create_ollama_client(get_config())


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


async def get_context_surgeon(
    knowledge_manager: KnowledgeGraphManager = Depends(),
) -> ContextSurgeon:
    """Return a ContextSurgeon for a given rules directory."""
    return ContextSurgeon(rules_dir=Path("rules"))


async def get_atomic_executor(
    ollama: OllamaClient = Depends(get_ollama_client),
    surgeon: ContextSurgeon = Depends(get_context_surgeon),
) -> AtomicExecutor:
    """Return an AtomicExecutor instance."""
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
) -> SelfHealingOrchestrator:
    """Return a SelfHealingOrchestrator instance."""
    cfg = get_config()
    rules_dir = Path("rules")
    ollama = create_ollama_client(cfg)
    teacher = TeacherClient(ollama_client=ollama)
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
    return TemplateRegistry(templates_dir=Path("templates"))


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


async def get_engine(
    gate: "ConfidenceGate" = Depends(get_confidence_gate),
    weaver: ResultWeaver = Depends(get_result_weaver),
    state_writer: StateFileWriter = Depends(get_state_writer),
    registry: TemplateRegistry = Depends(get_template_registry),
    kg: KnowledgeGraphManager = Depends(get_knowledge_manager),
) -> SpecForgeEngine:
    """Return a SpecForgeEngine singleton."""
    return SpecForgeEngine(
        confidence_gate=gate,
        result_weaver=weaver,
        state_writer=state_writer,
        template_registry=registry,
        knowledge_manager=kg,
    )
