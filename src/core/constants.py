"""Application-wide constants for SpecForge."""

# Retry configuration
MAX_RETRY_ATTEMPTS: int = 3
"""Global default max retry attempts for any operation."""

TIER1_MAX_RETRIES: int = 1
"""Max retries for SEV1 (critical) nodes — minimal, escalate fast."""

TIER2_MAX_RETRIES: int = 2
"""Max retries for SEV2 (regression) nodes — moderate retries."""

TIER3_THRESHOLD: int = 3
"""Consecutive failure count that triggers Deep Path execution mode."""

# Context and token budgets
DEFAULT_CONTEXT_TOKEN_BUDGET: int = 1500
"""Default per-node context window budget in tokens."""

KNOWLEDGE_GRAPH_MAX_DEPTH: int = 2
"""Max traversal depth when following [[wiki-links]] in knowledge graph."""

# Reasoning configuration
LOOKAHEAD_PATH_COUNT: int = 3
"""Number of hypothesis paths generated at inference-time for lookahead DAG."""

SELF_HEALING_FAILURE_THRESHOLD: int = 3
"""Consecutive failures on a node before self-healing loop is triggered."""

# Template schema
TEMPLATE_SCHEMA_VERSION: str = "1.0.0"
"""Version identifier for .ct.json cognitive template schema."""

# File names
STATE_FILE_NAME: str = "state.md"
"""Filename for the per-execution execution state Markdown output."""

GRAPH_REPORT_FILE: str = "graphify-out/GRAPH_REPORT.md"
"""Path to the graphify knowledge graph report."""

# Ollama defaults
OLLAMA_DEFAULT_MODEL: str = "llama3.2"
"""Default Ollama model for standard node execution."""

OLLAMA_TEACHER_MODEL: str = "llama3.1:8b"
"""Larger teacher model used for self-healing and deep reasoning paths."""

OLLAMA_TEMPERATURE: float = 0.3
"""Default temperature for Ollama generation calls (lower = more deterministic)."""

# Redis keys and TTL
REDIS_KEY_PREFIX: str = "specforge"
"""Namespace prefix for all Redis keys."""

REDIS_EXECUTION_TTL: int = 86400
"""TTL for execution state keys in Redis, in seconds (24 hours)."""

REDIS_CACHE_TTL: int = 3600
"""TTL for general cached data in Redis, in seconds (1 hour)."""
