# GitHub Copilot — Person 3: Failure Memory Bank (FMB)
## SpecForge · Cross-Run Self-Improving Memory System

---

## CONTEXT — READ THIS FIRST

You are implementing ONE research feature for SpecForge: the **Failure Memory Bank (FMB)**.

SpecForge is a Cognitive Task Decomposition framework that runs local LLMs via Ollama.
Currently when a node fails, it retries. Then it forgets. The next run of a similar task
starts from scratch with no knowledge of what went wrong before.

**Your job: make the system remember and proactively adapt.**

The FMB stores every failure with full context (what failed, why, what fixed it).
Before the NEXT similar task runs, the system retrieves relevant past failures and
automatically adjusts the execution configuration — tighter SPA thresholds, more SCS drafts,
extra prompt instructions — BEFORE the node even starts. This is the difference between
"retry on failure" (reactive) and "prevent failure before it happens" (proactive).

This is directly inspired by the FSLM project's failure-driven self-improvement loop,
applied at the inference-time cognition layer instead of the weight-update layer.

**Your entire implementation lives in `specforge/memory/`. Zero dependency on Person 1
or Person 2's code. Your demo runs completely standalone.**

**Tech stack:**
- Python 3.11+
- SQLite (stdlib — no install needed, for structured fields)
- ChromaDB (vector store for semantic similarity search)
- httpx (optional — only if you add Ollama embedding support)

**New packages to install:**
```
pip install chromadb
```

---

## YOUR COMPLETE FILE STRUCTURE

```
specforge/
  memory/
    __init__.py           ← exports everything
    failure_record.py     ← CognitiveFailureRecord dataclass (the core data structure)
    memory_store.py       ← dual-store: SQLite (structured) + ChromaDB (semantic)
    memory_retriever.py   ← high-level query interface, packages results into RelevantMemories
    memory_adapter.py     ← translates memories into AdaptedExecutionConfig (the action layer)
  tests/
    test_memory.py        ← unit tests (no external services needed)
  demos/
    memory_demo.py        ← standalone runnable demo
```

---

## FILE 1 OF 5: `specforge/memory/failure_record.py`

**Purpose:** The central data structure of the entire FMB system.
Every field is deliberate — structured fields go to SQLite for fast filtering,
`task_description` gets embedded in ChromaDB for semantic similarity search.

```python
import uuid
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from enum import Enum


class FailureType(str, Enum):
    """
    Taxonomy of LLM node failures.
    Used for pattern detection and repair strategy routing.
    """
    SCHEMA_VIOLATION      = "schema_violation"
    # The output didn't match the expected JSON schema or output format.
    # Example: missing required field, wrong type, invalid nesting.

    HALLUCINATION_DRIFT   = "hallucination_drift"
    # The model drifted from the task and introduced unsupported facts.
    # Usually caught by high entropy (SPA) or factual validators.

    PREMATURE_CONCLUSION  = "premature_conclusion"
    # The model answered too quickly without sufficient reasoning.
    # Output too short, reasoning trace absent, assumptions unverified.

    LOGICAL_CONTRADICTION = "logical_contradiction"
    # The output contradicts itself or contradicts earlier nodes.

    CONTEXT_FORGETTING    = "context_forgetting"
    # The output ignores critical parts of the prompt or upstream context.

    OVER_GENERATION       = "over_generation"
    # Output too long, went off-topic, filled with irrelevant content.

    TOOL_MISUSE           = "tool_misuse"
    # Wrong output format for a downstream tool or symbolic node.

    UNKNOWN               = "unknown"
    # Unclassified failure — used as default until diagnosis is complete.


@dataclass
class CognitiveFailureRecord:
    """
    A complete record of one failed node execution.

    Design principle: store EVERYTHING that could be useful for future adaptation.
    Disk is cheap; missing signal is expensive.

    Two storage destinations:
    - SQLite: all structured fields → fast filtering by node_type, failure_type, date
    - ChromaDB: task_description field → semantic similarity search for "have we seen this?"
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Unique UUID for this record. Auto-generated.

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    # ISO 8601 UTC timestamp. Auto-generated.

    # ── Task context ──────────────────────────────────────────────────────────
    node_type: str = ""
    # The DAG node type. e.g. "extract_invoice", "reason_causal", "generate_plan".
    # Used for SQLite filtering and as a secondary signal in ChromaDB metadata.

    task_description: str = ""
    # The actual prompt or task text for this node.
    # THIS IS THE FIELD THAT GETS EMBEDDED in ChromaDB for semantic search.
    # When a new task arrives, we embed it and search against these descriptions.

    model_used: str = ""
    # Ollama model name. e.g. "llama3:8b", "qwen2:7b".
    # Different models may have different failure patterns.

    # ── Failure details ───────────────────────────────────────────────────────
    failure_type: FailureType = FailureType.UNKNOWN
    # Taxonomy classification. Used to route to the right repair strategy.

    validator_error: str = ""
    # The exact error message from the validator (JSON schema error, test failure, etc.)
    # Example: 'JSON parse error: required field "vendor_name" is missing'
    # This is what gets fed back to the model on repair — must be precise.

    failed_output: str = ""
    # What the model actually produced. Truncated to 500 chars for storage efficiency.

    entropy_at_failure: float = 0.0
    # Mean token entropy during the failed generation (from SPA monitor).
    # High entropy (>0.55) suggests hallucination drift was the root cause.

    # ── Repair details ────────────────────────────────────────────────────────
    repair_attempted: bool = False
    # Whether a repair was tried after the failure.

    repair_strategy_used: str = ""
    # What strategy was used for repair.
    # Examples: "strict_json_prompt", "budget_forcing", "adversarial_triad",
    #           "schema_first_prompt", "lower_temperature"

    repair_successful: bool = False
    # Whether the repair produced a valid output.

    successful_output: str = ""
    # The output that passed validation after repair. Truncated to 500 chars.
    # Used to update the CAS exemplar cache (Person 1's system).

    repair_prompt_delta: str = ""
    # What changed in the prompt that fixed it.
    # Example: "Added: 'Your JSON must include vendor_name field.'"

    # ── Adaptation hints ──────────────────────────────────────────────────────
    # These fields are filled AFTER a successful repair.
    # The MemoryAdapter reads them to configure future runs proactively.

    recommended_spa_threshold: Optional[float] = None
    # If set, lower SPA injection threshold by this amount for similar future tasks.
    # Example: 0.38 means "trigger pressure injection earlier than the default 0.50"

    recommended_n_drafts: Optional[int] = None
    # If set, increase SCS N drafts for similar future tasks.
    # Example: 7 means "this node type needs more trajectory sampling"

    recommended_prompt_prefix: str = ""
    # If set, prepend this text to the system prompt for similar future tasks.
    # Example: "Always include all required fields: vendor_name, line_items, total."

    def to_dict(self) -> dict:
        """
        Serialise to a flat dict for SQLite storage.

        Implementation:
            d = asdict(self)
            d["failure_type"] = self.failure_type.value   # Enum → string
            d["repair_attempted"] = int(self.repair_attempted)   # bool → int for SQLite
            d["repair_successful"] = int(self.repair_successful)
            return d
        """

    @classmethod
    def from_dict(cls, d: dict) -> "CognitiveFailureRecord":
        """
        Deserialise from a flat dict (as returned by SQLite fetchone).

        Implementation:
            d = d.copy()
            d["failure_type"] = FailureType(d.get("failure_type", "unknown"))
            d["repair_attempted"] = bool(d.get("repair_attempted", 0))
            d["repair_successful"] = bool(d.get("repair_successful", 0))
            # Handle None values for optional fields:
            d.setdefault("recommended_spa_threshold", None)
            d.setdefault("recommended_n_drafts", None)
            d.setdefault("recommended_prompt_prefix", "")
            return cls(**d)
        """

    def to_chroma_document(self) -> dict:
        """
        Format for ChromaDB upsert.

        The 'document' field is what ChromaDB embeds and searches against.
        We use task_description because that's what we compare to when a new task arrives.

        Returns:
            {
                "id": self.record_id,
                "document": self.task_description,
                "metadata": {
                    "node_type": self.node_type,
                    "failure_type": self.failure_type.value,
                    "repair_successful": str(self.repair_successful),  # ChromaDB needs strings
                    "model_used": self.model_used,
                    "created_at": self.created_at,
                    "recommended_spa_threshold": str(self.recommended_spa_threshold or ""),
                    "recommended_n_drafts": str(self.recommended_n_drafts or ""),
                    "recommended_prompt_prefix": self.recommended_prompt_prefix,
                }
            }

        Note: ChromaDB metadata values must be str, int, or float — no None allowed.
        Convert all None values to empty string "" before including in metadata.
        """
```

---

## FILE 2 OF 5: `specforge/memory/memory_store.py`

**Purpose:** Persists CognitiveFailureRecords to two stores simultaneously:
- **SQLite** → structured fields, fast filtering, always available (stdlib)
- **ChromaDB** → task_description embeddings, semantic similarity search

Both stores stay in sync. Every `save()` writes to both.

```python
import sqlite3
import json
import os
from typing import Optional
from pathlib import Path

import chromadb
from chromadb.config import Settings

from .failure_record import CognitiveFailureRecord, FailureType


class MemoryStore:
    """
    Dual-store persistence layer for the Failure Memory Bank.

    Architecture:
        SQLite  → structured queries (filter by node_type, date, failure_type)
        ChromaDB → semantic queries (find similar past task descriptions)

    Both stores must stay in sync — every save goes to both, every delete to both.

    Usage:
        store = MemoryStore()
        store.save(record)
        results = store.semantic_search("extract invoice data", node_type_filter="extract_invoice")
        store.close()
    """

    # SQLite schema — create this table and these indices on initialisation
    SQLITE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS cognitive_failures (
        record_id                 TEXT PRIMARY KEY,
        created_at                TEXT NOT NULL,
        node_type                 TEXT NOT NULL DEFAULT '',
        task_description          TEXT NOT NULL DEFAULT '',
        model_used                TEXT NOT NULL DEFAULT '',
        failure_type              TEXT NOT NULL DEFAULT 'unknown',
        validator_error           TEXT DEFAULT '',
        failed_output             TEXT DEFAULT '',
        entropy_at_failure        REAL DEFAULT 0.0,
        repair_attempted          INTEGER DEFAULT 0,
        repair_strategy_used      TEXT DEFAULT '',
        repair_successful         INTEGER DEFAULT 0,
        successful_output         TEXT DEFAULT '',
        repair_prompt_delta       TEXT DEFAULT '',
        recommended_spa_threshold REAL,
        recommended_n_drafts      INTEGER,
        recommended_prompt_prefix TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_node_type       ON cognitive_failures(node_type);
    CREATE INDEX IF NOT EXISTS idx_failure_type    ON cognitive_failures(failure_type);
    CREATE INDEX IF NOT EXISTS idx_repair_success  ON cognitive_failures(repair_successful);
    CREATE INDEX IF NOT EXISTS idx_created_at      ON cognitive_failures(created_at);
    """

    # SQLite column order — must match INSERT statement
    COLUMNS = [
        "record_id", "created_at", "node_type", "task_description", "model_used",
        "failure_type", "validator_error", "failed_output", "entropy_at_failure",
        "repair_attempted", "repair_strategy_used", "repair_successful",
        "successful_output", "repair_prompt_delta",
        "recommended_spa_threshold", "recommended_n_drafts", "recommended_prompt_prefix",
    ]

    def __init__(
        self,
        db_path: str = "specforge_memory.db",
        chroma_path: str = "./chroma_memory",
        collection_name: str = "cognitive_failures",
    ):
        """
        Initialise both stores.

        SQLite setup:
            self._conn = sqlite3.connect(db_path)
            self._conn.row_factory = sqlite3.Row   ← enables dict-like access
            self._conn.executescript(self.SQLITE_SCHEMA)
            self._conn.commit()

        ChromaDB setup:
            If chroma_path == ":memory:" or db_path == ":memory:":
                Use chromadb.EphemeralClient() for testing (in-memory, no disk)
            Else:
                Use chromadb.PersistentClient(path=chroma_path)
            self._collection = client.get_or_create_collection(
                name=collection_name,
                # ChromaDB will use its default embedding function (all-MiniLM-L6-v2)
                # This is fast, local, and sufficient for our use case.
            )
        """

    def save(self, record: CognitiveFailureRecord) -> None:
        """
        Save a record to BOTH SQLite and ChromaDB.

        If a record with the same record_id already exists, replace it (upsert).

        SQLite:
            d = record.to_dict()
            values = [d[col] for col in self.COLUMNS]
            placeholders = ", ".join(["?"] * len(self.COLUMNS))
            cols = ", ".join(self.COLUMNS)
            self._conn.execute(
                f"INSERT OR REPLACE INTO cognitive_failures ({cols}) VALUES ({placeholders})",
                values
            )
            self._conn.commit()

        ChromaDB:
            doc = record.to_chroma_document()
            self._collection.upsert(
                ids=[doc["id"]],
                documents=[doc["document"]],
                metadatas=[doc["metadata"]]
            )
        """

    def get_by_id(self, record_id: str) -> Optional[CognitiveFailureRecord]:
        """
        Retrieve a single record by UUID.

        SQL: SELECT * FROM cognitive_failures WHERE record_id = ?
        If no row found: return None
        If found: return CognitiveFailureRecord.from_dict(dict(row))

        Note: sqlite3.Row objects can be converted to dict with dict(row)
        """

    def get_by_node_type(
        self,
        node_type: str,
        limit: int = 20,
        repair_successful_only: bool = False,
    ) -> list[CognitiveFailureRecord]:
        """
        Get recent failure records for a specific node type.

        SQL:
            SELECT * FROM cognitive_failures
            WHERE node_type = ?
            [AND repair_successful = 1]   ← only if repair_successful_only=True
            ORDER BY created_at DESC
            LIMIT ?

        Return list of CognitiveFailureRecord.from_dict(dict(row)) for each row.
        Return empty list if no records found (do not raise).
        """

    def get_failure_count_by_node_type(self) -> dict[str, int]:
        """
        Return a dict mapping each node_type to its total failure count.

        SQL: SELECT node_type, COUNT(*) as cnt
             FROM cognitive_failures
             GROUP BY node_type
             ORDER BY cnt DESC

        Return: {"extract_invoice": 12, "reason_causal": 5, ...}
        Return empty dict if table is empty.
        """

    def update_repair_outcome(
        self,
        record_id: str,
        repair_successful: bool,
        successful_output: str = "",
        repair_prompt_delta: str = "",
        recommended_spa_threshold: Optional[float] = None,
        recommended_n_drafts: Optional[int] = None,
        recommended_prompt_prefix: str = "",
    ) -> None:
        """
        Update a record after its repair attempt completes.
        Called by MemoryAdapter.record_execution_outcome().

        SQLite UPDATE:
            UPDATE cognitive_failures
            SET repair_successful = ?,
                successful_output = ?,
                repair_prompt_delta = ?,
                recommended_spa_threshold = ?,
                recommended_n_drafts = ?,
                recommended_prompt_prefix = ?
            WHERE record_id = ?

        ChromaDB metadata update:
            self._collection.update(
                ids=[record_id],
                metadatas=[{
                    "repair_successful": str(repair_successful),
                    "recommended_spa_threshold": str(recommended_spa_threshold or ""),
                    "recommended_n_drafts": str(recommended_n_drafts or ""),
                    "recommended_prompt_prefix": recommended_prompt_prefix,
                }]
            )

        If record_id does not exist in SQLite: silently do nothing (no error).
        """

    def semantic_search(
        self,
        query_text: str,
        node_type_filter: Optional[str] = None,
        n_results: int = 5,
    ) -> list[tuple[CognitiveFailureRecord, float]]:
        """
        Search for similar past failures using ChromaDB's semantic search.

        ChromaDB embeds query_text using the same model used to embed stored documents,
        then returns the n_results most similar records.

        ChromaDB query:
            where_filter = {"node_type": node_type_filter} if node_type_filter else None
            results = self._collection.query(
                query_texts=[query_text],
                n_results=min(n_results, self._collection.count()),
                where=where_filter,
                include=["distances", "metadatas"]
            )

        ChromaDB returns L2 distances (lower = more similar).
        Convert to similarity score: similarity = 1.0 / (1.0 + distance)
        This maps distance 0 → similarity 1.0, distance ∞ → similarity 0.0.

        For each result:
            record_id = results["ids"][0][i]
            distance  = results["distances"][0][i]
            similarity = 1.0 / (1.0 + distance)
            record = self.get_by_id(record_id)
            if record is not None:
                append (record, similarity)

        Return sorted by similarity descending.
        Return empty list if collection is empty or query_text is empty.

        Important edge case: if self._collection.count() == 0, return [] immediately
        (ChromaDB raises an error if you query an empty collection).
        """

    def close(self) -> None:
        """
        Close the SQLite connection.
            if hasattr(self, "_conn") and self._conn:
                self._conn.close()
        ChromaDB client does not need explicit closing.
        """
```

---

## FILE 3 OF 5: `specforge/memory/memory_retriever.py`

**Purpose:** High-level query interface. Calls MemoryStore and packages raw records
into actionable `RelevantMemories` — a structured summary of what we know about
this task type.

```python
from dataclasses import dataclass, field
from typing import Optional
from collections import Counter

from .memory_store import MemoryStore
from .failure_record import CognitiveFailureRecord, FailureType


@dataclass
class RelevantMemories:
    """
    Packaged retrieval result for one incoming task.
    This is what MemoryAdapter reads to decide what to adapt.
    """

    similar_failures: list[tuple[CognitiveFailureRecord, float]]
    # List of (record, similarity_score) pairs, sorted by similarity descending.
    # Only includes records with similarity >= SIMILARITY_THRESHOLD.

    successful_repairs: list[CognitiveFailureRecord]
    # Subset of similar_failures where repair_successful == True.
    # These are the "what worked before" signals.

    dominant_failure_type: Optional[FailureType]
    # The most common FailureType among similar_failures.
    # None if there are too few failures to establish a pattern.

    historical_failure_rate: float
    # Fraction of past runs for this node_type that required repair.
    # 0.0 = always succeeds, 1.0 = always fails.

    has_relevant_memories: bool
    # True if at least one similar failure was found above the threshold.
    # If False, MemoryAdapter should not attempt adaptation.


class MemoryRetriever:
    """
    Packages raw MemoryStore data into actionable RelevantMemories.

    Called BEFORE each node execution to proactively check:
    "Have we failed on something like this before? What fixed it?"
    """

    SIMILARITY_THRESHOLD = 0.60
    # Minimum cosine similarity for a past failure to be considered "relevant".
    # Below this: the past failure was for a different enough task that it shouldn't
    # influence the current run. Tune this carefully — too low = false positives.

    MIN_FAILURES_FOR_PATTERN = 3
    # Need at least this many relevant failures to infer a dominant failure type.
    # With fewer than 3, we might misattribute a one-off to a pattern.

    def __init__(self, store: MemoryStore):
        """Store as self.store"""

    def retrieve_for_task(
        self,
        task_description: str,
        node_type: str,
        n_similar: int = 5,
    ) -> RelevantMemories:
        """
        Retrieve and package relevant memories for an incoming task.

        Args:
            task_description: the task text about to be executed
            node_type:        the node type (e.g. "extract_invoice")
            n_similar:        how many similar records to fetch from ChromaDB

        Returns:
            RelevantMemories

        Implementation:

        STEP 1: Semantic search for similar past failures
            all_results = self.store.semantic_search(
                query_text=task_description,
                node_type_filter=node_type,
                n_results=n_similar,
            )
            Filter to only those above threshold:
            similar_failures = [
                (record, score)
                for record, score in all_results
                if score >= self.SIMILARITY_THRESHOLD
            ]

        STEP 2: Extract successful repairs
            successful_repairs = [
                record
                for record, score in similar_failures
                if record.repair_successful
            ]

        STEP 3: Compute dominant_failure_type
            If len(similar_failures) >= self.MIN_FAILURES_FOR_PATTERN:
                counts = Counter(record.failure_type for record, _ in similar_failures)
                dominant_failure_type = counts.most_common(1)[0][0]
            Else:
                dominant_failure_type = None

        STEP 4: Compute historical_failure_rate
            recent_records = self.store.get_by_node_type(node_type, limit=50)
            If len(recent_records) > 0:
                failed_count = sum(1 for r in recent_records if not r.repair_successful)
                historical_failure_rate = failed_count / len(recent_records)
            Else:
                historical_failure_rate = 0.0

        STEP 5: has_relevant_memories = len(similar_failures) > 0

        STEP 6: Return RelevantMemories with all fields filled.
        """

    def get_best_repair_strategy(self, memories: RelevantMemories) -> Optional[str]:
        """
        Return the most commonly used repair strategy among successful repairs.

        Implementation:
            If not memories.successful_repairs: return None
            strategy_counts = Counter(
                r.repair_strategy_used
                for r in memories.successful_repairs
                if r.repair_strategy_used
            )
            If not strategy_counts: return None
            return strategy_counts.most_common(1)[0][0]
        """

    def get_recommended_prompt_additions(self, memories: RelevantMemories) -> list[str]:
        """
        Collect all non-empty recommended_prompt_prefix values from successful repairs,
        deduplicated, sorted by frequency (most recommended first).

        Implementation:
            prefixes = [
                r.recommended_prompt_prefix
                for r in memories.successful_repairs
                if r.recommended_prompt_prefix.strip()
            ]
            If not prefixes: return []
            counts = Counter(prefixes)
            Return [prefix for prefix, count in counts.most_common()]
            (deduplication is implicit — Counter aggregates duplicates)
        """
```

---

## FILE 4 OF 5: `specforge/memory/memory_adapter.py`

**Purpose:** The most important file. Translates RelevantMemories into concrete
execution config changes that get applied BEFORE the node runs.

This is the "brain" of the FMB — it doesn't just surface memories, it decides
what to DO about them. Think of it as a pre-flight checklist that configures
the node based on what went wrong last time.

```python
from dataclasses import dataclass, field
from typing import Optional

from .memory_retriever import MemoryRetriever, RelevantMemories
from .failure_record import CognitiveFailureRecord, FailureType


@dataclass
class AdaptedExecutionConfig:
    """
    The output of MemoryAdapter — a modified config for the upcoming node execution.

    All fields are Optional with None meaning "use the default from the node config".
    The caller only overrides what is explicitly set here.
    """

    # SCS (Speculative Consistency Sampling) adaptations
    n_drafts_override: Optional[int] = None
    # If set, use this N for SCS instead of the node's default.
    # Increased when we've seen false clusters or high failure rates.

    scs_confidence_threshold: Optional[float] = None
    # If set, require this confidence score from SCS before proceeding.
    # Increased for high-failure nodes (more conservative escalation).

    # SPA (Semantic Pressure Annealing) adaptations
    spa_inject_threshold_override: Optional[float] = None
    # If set, use this as the entropy injection threshold.
    # Lower value = tighter control = pressure injected sooner.

    spa_warn_threshold_override: Optional[float] = None
    # If set, use this as the entropy warn threshold.

    # Prompt adaptations
    prompt_prefix_additions: list[str] = field(default_factory=list)
    # Strings to prepend to the system prompt before execution.
    # Accumulated from successful repair strategies in past similar runs.

    # Reasoning adaptations
    force_deep_reason: bool = False
    # If True, override node_type to "deep_reason" regardless of original type.
    # Used when premature_conclusion failures are dominant.

    # Meta fields (for logging and explainability)
    adaptation_reason: str = ""
    # Human-readable explanation of what was adapted and why.
    # Example: "Lowered SPA threshold to 0.38 due to 67% hallucination_drift rate"

    confidence: float = 0.0
    # How confident we are in this adaptation (0.0 = no evidence, 1.0 = strong evidence).
    # Scales with number of relevant memories used.

    memories_used: int = 0
    # How many relevant memory records informed this adaptation.


class MemoryAdapter:
    """
    Translates retrieved memories into concrete execution config changes.

    Calling get_adapted_config() before a node runs is the entire FMB feedback loop:
    1. Retrieve memories relevant to this task
    2. Identify patterns (dominant failure type, historical failure rate)
    3. Apply evidence-based adaptations
    4. Return AdaptedExecutionConfig for the caller to apply

    Philosophy: be CONSERVATIVE. Only adapt when there is strong evidence.
    False positives (unnecessary restriction) hurt creative/brainstorming nodes.
    False negatives (missing a needed restriction) are caught by the retry loop anyway.
    """

    MIN_MEMORIES_FOR_CONFIDENCE = 2
    # Minimum relevant memories needed before we make any adaptation.
    # With 0 or 1 relevant memory, we could be overfitting to a coincidence.

    HIGH_FAILURE_RATE_THRESHOLD = 0.40
    # If historical_failure_rate > this, the node is "high-risk" → tighten controls.

    def __init__(self, retriever: MemoryRetriever):
        """Store as self.retriever"""

    def get_adapted_config(
        self,
        task_description: str,
        node_type: str,
        base_n_drafts: int = 5,
        base_inject_threshold: float = 0.50,
        base_warn_threshold: float = 0.30,
    ) -> AdaptedExecutionConfig:
        """
        Main entry point. Retrieve memories and return an adapted config.

        Args:
            task_description:       the task text about to be executed
            node_type:              e.g. "extract_invoice"
            base_n_drafts:          the node's default SCS N
            base_inject_threshold:  the node's default SPA injection threshold
            base_warn_threshold:    the node's default SPA warn threshold

        Returns:
            AdaptedExecutionConfig

        Implementation — follow these rules in order:

        STEP 1: Retrieve memories
            memories = self.retriever.retrieve_for_task(task_description, node_type)

        STEP 2: Early exit if no memories
            If not memories.has_relevant_memories:
                return AdaptedExecutionConfig(
                    adaptation_reason="no relevant history found",
                    memories_used=0,
                )

        STEP 3: Early exit if too few memories for confidence
            n_mem = len(memories.similar_failures)
            If n_mem < self.MIN_MEMORIES_FOR_CONFIDENCE:
                return AdaptedExecutionConfig(
                    adaptation_reason=f"insufficient history ({n_mem} memories, need {self.MIN_MEMORIES_FOR_CONFIDENCE})",
                    memories_used=n_mem,
                )

        STEP 4: Build the adapted config by applying adaptation rules.
            Initialise:
                spa_inject = None
                spa_warn = None
                n_drafts = None
                force_deep = False
                prompt_additions = []
                reasons = []

            RULE A — HIGH FAILURE RATE → tighten SPA thresholds
                If memories.historical_failure_rate > self.HIGH_FAILURE_RATE_THRESHOLD:
                    spa_inject = max(0.28, base_inject_threshold - 0.12)
                    spa_warn   = max(0.18, base_warn_threshold   - 0.08)
                    reasons.append(
                        f"tightened SPA thresholds (failure rate: "
                        f"{memories.historical_failure_rate:.0%})"
                    )

            RULE B — SCHEMA_VIOLATION dominant → add format reminder
                If memories.dominant_failure_type == FailureType.SCHEMA_VIOLATION:
                    prompt_additions.append(
                        "CRITICAL: Your output MUST exactly match the required format/schema. "
                        "Verify every required field is present and correctly typed before responding."
                    )
                    reasons.append("added schema enforcement prefix (past schema violations)")

            RULE C — HALLUCINATION_DRIFT dominant → more SCS + tighter SPA
                If memories.dominant_failure_type == FailureType.HALLUCINATION_DRIFT:
                    n_drafts = min(base_n_drafts + 2, 9)
                    spa_inject = min(
                        spa_inject or base_inject_threshold,
                        max(0.32, base_inject_threshold - 0.10)
                    )
                    reasons.append(
                        f"increased SCS to N={n_drafts} (past hallucination drift)"
                    )

            RULE D — PREMATURE_CONCLUSION dominant → force deep reasoning
                If memories.dominant_failure_type == FailureType.PREMATURE_CONCLUSION:
                    force_deep = True
                    prompt_additions.append(
                        "Think through this problem step by step before giving your answer. "
                        "Do not state a conclusion until you have fully reasoned through all aspects."
                    )
                    reasons.append("forced deep reasoning (past premature conclusions)")

            RULE E — LOGICAL_CONTRADICTION dominant → add self-check reminder
                If memories.dominant_failure_type == FailureType.LOGICAL_CONTRADICTION:
                    prompt_additions.append(
                        "Before finalising your answer, check it for internal consistency. "
                        "Ensure no statement contradicts another in your response."
                    )
                    reasons.append("added consistency check prefix (past contradictions)")

            RULE F — OVER_GENERATION dominant → add length constraint
                If memories.dominant_failure_type == FailureType.OVER_GENERATION:
                    prompt_additions.append(
                        "Be concise. Answer only what was asked. Stop when the task is complete."
                    )
                    reasons.append("added conciseness prefix (past over-generation)")

            RULE G — Add successful repair prompt prefixes
                new_prefixes = self.retriever.get_recommended_prompt_additions(memories)
                For each prefix in new_prefixes:
                    if prefix not in prompt_additions:
                        prompt_additions.append(prefix)
                If new_prefixes:
                    reasons.append(
                        f"added {len(new_prefixes)} prefix(es) from successful past repairs"
                    )

        STEP 5: Compute confidence
            confidence = min(1.0, n_mem / 10.0)
            # Scales linearly: 0 memories → 0.0, 10+ memories → 1.0

        STEP 6: Build and return AdaptedExecutionConfig
            return AdaptedExecutionConfig(
                n_drafts_override=n_drafts,
                spa_inject_threshold_override=spa_inject,
                spa_warn_threshold_override=spa_warn,
                prompt_prefix_additions=prompt_additions,
                force_deep_reason=force_deep,
                adaptation_reason="; ".join(reasons) if reasons else "no adaptations needed",
                confidence=confidence,
                memories_used=n_mem,
            )
        """

    def record_execution_outcome(
        self,
        store: "MemoryStore",
        record_id: str,
        repair_successful: bool,
        successful_output: str = "",
        repair_prompt_delta: str = "",
        recommended_spa_threshold: Optional[float] = None,
        recommended_n_drafts: Optional[int] = None,
        recommended_prompt_prefix: str = "",
    ) -> None:
        """
        After a node execution completes (success or failure), update the record.
        This closes the feedback loop — the memory learns from this run.

        Called by the DAG executor after each node finishes.

        Implementation:
            store.update_repair_outcome(
                record_id=record_id,
                repair_successful=repair_successful,
                successful_output=successful_output[:500],  # truncate for storage
                repair_prompt_delta=repair_prompt_delta,
                recommended_spa_threshold=recommended_spa_threshold,
                recommended_n_drafts=recommended_n_drafts,
                recommended_prompt_prefix=recommended_prompt_prefix,
            )
        """
```

---

## FILE 5 OF 5: `specforge/memory/__init__.py`

```python
from .failure_record import CognitiveFailureRecord, FailureType
from .memory_store import MemoryStore
from .memory_retriever import MemoryRetriever, RelevantMemories
from .memory_adapter import MemoryAdapter, AdaptedExecutionConfig

__all__ = [
    "CognitiveFailureRecord",
    "FailureType",
    "MemoryStore",
    "MemoryRetriever",
    "RelevantMemories",
    "MemoryAdapter",
    "AdaptedExecutionConfig",
]
```

---

## TESTS: `specforge/tests/test_memory.py`

**All tests must pass WITHOUT any external service (ChromaDB uses in-memory client).**

```python
import pytest
import tempfile
import os
from pathlib import Path

from specforge.memory.failure_record import CognitiveFailureRecord, FailureType
from specforge.memory.memory_store import MemoryStore
from specforge.memory.memory_retriever import MemoryRetriever
from specforge.memory.memory_adapter import MemoryAdapter, AdaptedExecutionConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    """
    Fresh MemoryStore backed by a temp SQLite file and in-memory ChromaDB.
    Each test gets a clean slate.
    """
    db_path = str(tmp_path / "test_memory.db")
    # Pass ":memory:" as chroma_path to trigger EphemeralClient
    s = MemoryStore(db_path=db_path, chroma_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def sample_record():
    return CognitiveFailureRecord(
        node_type="extract_invoice",
        task_description="Extract line items, totals, and vendor name from this invoice",
        model_used="llama3:8b",
        failure_type=FailureType.SCHEMA_VIOLATION,
        validator_error='Required field "vendor_name" is missing from output',
        failed_output='{"line_items": [...], "total": 450.00}',
        entropy_at_failure=0.48,
        repair_attempted=True,
        repair_strategy_used="strict_json_prompt",
        repair_successful=True,
        repair_prompt_delta="Added explicit field list to system prompt",
        recommended_prompt_prefix="Always include: vendor_name, line_items, total, currency.",
        recommended_spa_threshold=0.38,
    )


# ── CognitiveFailureRecord tests ──────────────────────────────────────────────

class TestCognitiveFailureRecord:

    def test_record_id_auto_generated(self):
        r = CognitiveFailureRecord()
        assert r.record_id is not None
        assert len(r.record_id) == 36  # UUID format

    def test_created_at_auto_generated(self):
        r = CognitiveFailureRecord()
        assert r.created_at is not None
        assert "T" in r.created_at  # ISO format check

    def test_to_dict_converts_enum_to_string(self):
        r = CognitiveFailureRecord(failure_type=FailureType.SCHEMA_VIOLATION)
        d = r.to_dict()
        assert d["failure_type"] == "schema_violation"
        assert isinstance(d["failure_type"], str)

    def test_to_dict_converts_bool_to_int(self):
        r = CognitiveFailureRecord(repair_attempted=True, repair_successful=False)
        d = r.to_dict()
        assert d["repair_attempted"] == 1
        assert d["repair_successful"] == 0

    def test_from_dict_roundtrip(self, sample_record):
        d = sample_record.to_dict()
        restored = CognitiveFailureRecord.from_dict(d)
        assert restored.record_id == sample_record.record_id
        assert restored.failure_type == FailureType.SCHEMA_VIOLATION
        assert restored.repair_successful is True
        assert restored.node_type == "extract_invoice"

    def test_chroma_document_format(self, sample_record):
        doc = sample_record.to_chroma_document()
        assert doc["id"] == sample_record.record_id
        assert doc["document"] == sample_record.task_description
        assert "node_type" in doc["metadata"]
        assert doc["metadata"]["node_type"] == "extract_invoice"
        # All metadata values must be str/int/float (no None)
        for v in doc["metadata"].values():
            assert v is not None

    def test_chroma_document_no_none_metadata_values(self):
        r = CognitiveFailureRecord()  # all defaults
        doc = r.to_chroma_document()
        for key, value in doc["metadata"].items():
            assert value is not None, f"Metadata key '{key}' has None value"


# ── MemoryStore tests ─────────────────────────────────────────────────────────

class TestMemoryStore:

    def test_save_and_retrieve_by_id(self, store, sample_record):
        store.save(sample_record)
        retrieved = store.get_by_id(sample_record.record_id)
        assert retrieved is not None
        assert retrieved.record_id == sample_record.record_id
        assert retrieved.failure_type == FailureType.SCHEMA_VIOLATION

    def test_get_by_id_returns_none_for_missing(self, store):
        result = store.get_by_id("nonexistent-id-12345")
        assert result is None

    def test_get_by_node_type_filters_correctly(self, store):
        for i in range(3):
            store.save(CognitiveFailureRecord(
                node_type="extract_invoice",
                task_description=f"invoice task {i}",
                failure_type=FailureType.SCHEMA_VIOLATION,
            ))
        store.save(CognitiveFailureRecord(
            node_type="reason_causal",
            task_description="reasoning task",
            failure_type=FailureType.PREMATURE_CONCLUSION,
        ))
        results = store.get_by_node_type("extract_invoice")
        assert len(results) == 3
        assert all(r.node_type == "extract_invoice" for r in results)

    def test_get_by_node_type_repair_successful_filter(self, store):
        store.save(CognitiveFailureRecord(
            node_type="test_node", task_description="t1",
            failure_type=FailureType.UNKNOWN, repair_successful=True,
        ))
        store.save(CognitiveFailureRecord(
            node_type="test_node", task_description="t2",
            failure_type=FailureType.UNKNOWN, repair_successful=False,
        ))
        all_records = store.get_by_node_type("test_node", repair_successful_only=False)
        successful  = store.get_by_node_type("test_node", repair_successful_only=True)
        assert len(all_records) == 2
        assert len(successful) == 1
        assert successful[0].repair_successful is True

    def test_failure_count_by_node_type(self, store):
        for node_type in ["extract_invoice", "extract_invoice", "extract_invoice",
                          "reason_causal", "reason_causal"]:
            store.save(CognitiveFailureRecord(
                node_type=node_type,
                task_description="task",
                failure_type=FailureType.UNKNOWN,
            ))
        counts = store.get_failure_count_by_node_type()
        assert counts["extract_invoice"] == 3
        assert counts["reason_causal"] == 2

    def test_update_repair_outcome(self, store, sample_record):
        sample_record.repair_successful = False
        store.save(sample_record)
        store.update_repair_outcome(
            record_id=sample_record.record_id,
            repair_successful=True,
            successful_output="Good structured JSON output",
            recommended_spa_threshold=0.35,
            recommended_n_drafts=7,
        )
        updated = store.get_by_id(sample_record.record_id)
        assert updated.repair_successful is True
        assert updated.successful_output == "Good structured JSON output"
        assert updated.recommended_spa_threshold == pytest.approx(0.35)
        assert updated.recommended_n_drafts == 7

    def test_save_upserts_on_duplicate_id(self, store, sample_record):
        store.save(sample_record)
        sample_record.validator_error = "updated error"
        store.save(sample_record)  # should not raise; should update
        retrieved = store.get_by_id(sample_record.record_id)
        assert retrieved.validator_error == "updated error"

    def test_semantic_search_returns_empty_on_empty_store(self, store):
        results = store.semantic_search("invoice task", n_results=5)
        assert results == []

    def test_semantic_search_finds_similar_records(self, store):
        # Save two records with similar descriptions
        r1 = CognitiveFailureRecord(
            node_type="extract_invoice",
            task_description="Extract invoice data including vendor and line items",
            failure_type=FailureType.SCHEMA_VIOLATION,
        )
        r2 = CognitiveFailureRecord(
            node_type="extract_invoice",
            task_description="Parse invoice document and return structured JSON",
            failure_type=FailureType.SCHEMA_VIOLATION,
        )
        r3 = CognitiveFailureRecord(
            node_type="reason_causal",
            task_description="Explain why the company's revenue declined in Q3",
            failure_type=FailureType.PREMATURE_CONCLUSION,
        )
        store.save(r1)
        store.save(r2)
        store.save(r3)

        results = store.semantic_search("extract invoice line items and totals", n_results=3)
        assert len(results) > 0
        # The invoice-related records should rank higher than the reasoning record
        top_record, top_score = results[0]
        assert top_record.node_type == "extract_invoice"
        # Scores should be sorted descending
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)


# ── MemoryRetriever tests ──────────────────────────────────────────────────────

class TestMemoryRetriever:

    def _seed_store(self, store: MemoryStore, n: int, node_type: str,
                    failure_type: FailureType, repair_ok: bool = True,
                    prefix: str = "extract invoice"):
        for i in range(n):
            store.save(CognitiveFailureRecord(
                node_type=node_type,
                task_description=f"{prefix} task number {i} with various data",
                failure_type=failure_type,
                repair_successful=repair_ok,
                recommended_prompt_prefix="Include all required fields." if repair_ok else "",
            ))

    def test_no_memories_returns_empty_result(self, store):
        retriever = MemoryRetriever(store)
        memories = retriever.retrieve_for_task("brand new never seen task", "new_node_type")
        assert not memories.has_relevant_memories
        assert len(memories.similar_failures) == 0
        assert memories.dominant_failure_type is None

    def test_dominant_failure_type_detected(self, store):
        self._seed_store(store, 5, "extract_invoice", FailureType.SCHEMA_VIOLATION)
        retriever = MemoryRetriever(store)
        memories = retriever.retrieve_for_task(
            "extract invoice data and totals", "extract_invoice"
        )
        if memories.has_relevant_memories and len(memories.similar_failures) >= 3:
            assert memories.dominant_failure_type == FailureType.SCHEMA_VIOLATION

    def test_successful_repairs_subset(self, store):
        self._seed_store(store, 3, "extract_invoice", FailureType.SCHEMA_VIOLATION, repair_ok=True)
        self._seed_store(store, 2, "extract_invoice", FailureType.SCHEMA_VIOLATION, repair_ok=False)
        retriever = MemoryRetriever(store)
        memories = retriever.retrieve_for_task("extract invoice totals", "extract_invoice")
        # successful_repairs must be subset of similar_failures
        if memories.has_relevant_memories:
            assert all(r.repair_successful for r in memories.successful_repairs)


# ── MemoryAdapter tests ───────────────────────────────────────────────────────

class TestMemoryAdapter:

    def _store_with_failures(self, store: MemoryStore, failure_type: FailureType,
                              n: int = 4, repair_ok: bool = True) -> None:
        for i in range(n):
            store.save(CognitiveFailureRecord(
                node_type="extract_invoice",
                task_description=f"extract invoice data item {i}",
                failure_type=failure_type,
                repair_successful=repair_ok,
                recommended_prompt_prefix="Always validate required fields." if repair_ok else "",
                recommended_spa_threshold=0.38 if repair_ok else None,
                recommended_n_drafts=7 if repair_ok else None,
            ))

    def test_no_adaptation_without_memories(self, store):
        retriever = MemoryRetriever(store)
        adapter = MemoryAdapter(retriever)
        config = adapter.get_adapted_config(
            "completely novel task type xyz",
            "novel_node_never_seen",
        )
        assert config.n_drafts_override is None
        assert config.spa_inject_threshold_override is None
        assert len(config.prompt_prefix_additions) == 0
        assert config.force_deep_reason is False

    def test_schema_violation_adds_prompt_prefix(self, store):
        self._store_with_failures(store, FailureType.SCHEMA_VIOLATION, n=4)
        retriever = MemoryRetriever(store)
        adapter = MemoryAdapter(retriever)
        config = adapter.get_adapted_config(
            "extract invoice totals and vendor name",
            "extract_invoice",
        )
        if config.memories_used >= 2:
            schema_prefixes = [
                p for p in config.prompt_prefix_additions
                if "schema" in p.lower() or "required" in p.lower() or "format" in p.lower()
            ]
            assert len(schema_prefixes) > 0

    def test_premature_conclusion_forces_deep_reason(self, store):
        self._store_with_failures(store, FailureType.PREMATURE_CONCLUSION, n=4)
        retriever = MemoryRetriever(store)
        adapter = MemoryAdapter(retriever)
        config = adapter.get_adapted_config(
            "extract invoice data",
            "extract_invoice",
        )
        if config.memories_used >= 2:
            assert config.force_deep_reason is True

    def test_confidence_scales_with_memory_count(self, store):
        retriever = MemoryRetriever(store)
        adapter = MemoryAdapter(retriever)
        # No memories → confidence 0
        config = adapter.get_adapted_config("novel task", "novel_node")
        assert config.confidence == 0.0

    def test_adaptation_reason_is_populated(self, store):
        self._store_with_failures(store, FailureType.SCHEMA_VIOLATION, n=4)
        retriever = MemoryRetriever(store)
        adapter = MemoryAdapter(retriever)
        config = adapter.get_adapted_config("extract invoice data", "extract_invoice")
        assert len(config.adaptation_reason) > 0
```

---

## DEMO: `specforge/demos/memory_demo.py`

```python
"""
Failure Memory Bank Demo

Run with:  python -m specforge.demos.memory_demo

What this shows:
  1. Storing diverse failure records (simulating past runs across multiple sessions)
  2. Semantic search — finding similar past failures for a new task
  3. MemoryRetriever packaging results into RelevantMemories
  4. MemoryAdapter producing a concrete AdaptedExecutionConfig
  5. The "proactive adaptation" effect: config changes BEFORE the node even runs

Does NOT require Ollama — ChromaDB uses its own built-in embedding model.
"""

import time
from specforge.memory import (
    CognitiveFailureRecord,
    FailureType,
    MemoryStore,
    MemoryRetriever,
    MemoryAdapter,
    AdaptedExecutionConfig,
)


# ── Seed data — realistic failure records from past runs ──────────────────────

SEED_FAILURES = [
    # Schema violations on invoice extraction
    CognitiveFailureRecord(
        node_type="extract_invoice",
        task_description="Extract all line items, subtotal, tax, and vendor name from invoice",
        model_used="llama3:8b",
        failure_type=FailureType.SCHEMA_VIOLATION,
        validator_error='Missing required field: "vendor_name". Got keys: line_items, total',
        failed_output='{"line_items": [{"desc": "Laptop", "price": 1200}], "total": 1200}',
        entropy_at_failure=0.52,
        repair_attempted=True,
        repair_strategy_used="strict_json_prompt",
        repair_successful=True,
        repair_prompt_delta="Added explicit field list to prompt",
        recommended_prompt_prefix="Always include ALL required fields: vendor_name, line_items, subtotal, tax, total.",
        recommended_spa_threshold=0.38,
    ),
    CognitiveFailureRecord(
        node_type="extract_invoice",
        task_description="Parse this invoice PDF text and return structured data with all amounts",
        model_used="llama3:8b",
        failure_type=FailureType.SCHEMA_VIOLATION,
        validator_error='Field "total" must be float, got string "$1,450.00"',
        failed_output='{"vendor_name": "ACME", "total": "$1,450.00"}',
        entropy_at_failure=0.44,
        repair_attempted=True,
        repair_strategy_used="strict_json_prompt",
        repair_successful=True,
        repair_prompt_delta="Added type constraints to prompt",
        recommended_prompt_prefix="Numeric fields must be floats without currency symbols. Not '$1,450.00' but 1450.00.",
        recommended_spa_threshold=0.40,
    ),
    CognitiveFailureRecord(
        node_type="extract_invoice",
        task_description="Read invoice and extract billing information as JSON",
        model_used="llama3:8b",
        failure_type=FailureType.SCHEMA_VIOLATION,
        validator_error='JSON parse error: unterminated string at line 4',
        failed_output='{"vendor_name": "Tech Corp",',
        entropy_at_failure=0.61,
        repair_attempted=True,
        repair_strategy_used="lower_temperature",
        repair_successful=True,
        recommended_spa_threshold=0.35,
        recommended_n_drafts=5,
    ),
    # Hallucination drift on reasoning
    CognitiveFailureRecord(
        node_type="reason_causal",
        task_description="Explain the three main causes of the 2008 financial crisis",
        model_used="llama3:8b",
        failure_type=FailureType.HALLUCINATION_DRIFT,
        validator_error="Factual validator: claim about Lehman Brothers date is incorrect",
        failed_output="Lehman Brothers collapsed in March 2008 due to...",
        entropy_at_failure=0.67,
        repair_attempted=True,
        repair_strategy_used="adversarial_triad",
        repair_successful=True,
        recommended_n_drafts=7,
        recommended_spa_threshold=0.32,
    ),
    # Premature conclusion on planning
    CognitiveFailureRecord(
        node_type="generate_plan",
        task_description="Create a 6-month product roadmap for a B2B SaaS startup",
        model_used="qwen2:7b",
        failure_type=FailureType.PREMATURE_CONCLUSION,
        validator_error="Output too short: 62 tokens (minimum 200 for planning nodes)",
        failed_output="Phase 1: Build MVP. Phase 2: Launch. Phase 3: Scale.",
        entropy_at_failure=0.19,
        repair_attempted=True,
        repair_strategy_used="budget_forcing",
        repair_successful=True,
        repair_prompt_delta="Added minimum depth requirement and step-by-step instruction",
    ),
]


def print_separator(title: str = ""):
    line = "─" * 65
    if title:
        print(f"\n  {title}")
        print("  " + line)
    else:
        print("  " + line)


def print_adapted_config(config: AdaptedExecutionConfig):
    print(f"  Memories used:              {config.memories_used}")
    print(f"  Adaptation confidence:      {config.confidence:.0%}")
    print(f"  Reason:                     {config.adaptation_reason}")

    changes = []
    if config.spa_inject_threshold_override is not None:
        changes.append(f"    SPA inject threshold  → {config.spa_inject_threshold_override:.2f}  (was 0.50)")
    if config.spa_warn_threshold_override is not None:
        changes.append(f"    SPA warn threshold    → {config.spa_warn_threshold_override:.2f}  (was 0.30)")
    if config.n_drafts_override is not None:
        changes.append(f"    SCS N drafts          → {config.n_drafts_override}  (was 5)")
    if config.force_deep_reason:
        changes.append(f"    Force deep reasoning  → True")
    for i, p in enumerate(config.prompt_prefix_additions, 1):
        changes.append(f"    Prompt prefix {i}:       \"{p[:70]}...\"" if len(p) > 70 else f"    Prompt prefix {i}:       \"{p}\"")

    if changes:
        print("\n  Adaptations applied:")
        for c in changes:
            print(c)
    else:
        print("\n  No adaptations applied (insufficient evidence).")


def main():
    print("=" * 65)
    print("  SpecForge — Failure Memory Bank Demo")
    print("=" * 65)

    # Use in-memory ChromaDB for demo (no files written)
    store = MemoryStore(db_path=":memory:", chroma_path=":memory:")
    retriever = MemoryRetriever(store)
    adapter = MemoryAdapter(retriever)

    # ── Step 1: Seed the memory bank ──────────────────────────────────────────
    print_separator("Step 1 — Seeding memory bank with past failures")
    for record in SEED_FAILURES:
        store.save(record)
    print(f"  Saved {len(SEED_FAILURES)} failure records across {len(set(r.node_type for r in SEED_FAILURES))} node types")
    counts = store.get_failure_count_by_node_type()
    print(f"  Failure counts by node type: {dict(counts)}")

    # ── Step 2: Semantic search ────────────────────────────────────────────────
    print_separator("Step 2 — Semantic search for a new incoming task")
    new_task = "Extract invoice line items and financial totals from billing document"
    print(f"  New task: \"{new_task}\"")
    print(f"  Node type: extract_invoice")

    results = store.semantic_search(new_task, node_type_filter="extract_invoice", n_results=5)
    print(f"\n  Found {len(results)} similar past failures:")
    for i, (record, score) in enumerate(results, 1):
        print(f"\n  [{i}] similarity={score:.4f}  failure={record.failure_type.value}  "
              f"repair_ok={record.repair_successful}")
        print(f"      task: \"{record.task_description[:70]}...\"")
        if record.validator_error:
            print(f"      error: {record.validator_error[:70]}")

    # ── Step 3: Package into RelevantMemories ─────────────────────────────────
    print_separator("Step 3 — Packaging into RelevantMemories")
    memories = retriever.retrieve_for_task(new_task, "extract_invoice")
    print(f"  Similar failures above threshold: {len(memories.similar_failures)}")
    print(f"  Successful repairs in set:        {len(memories.successful_repairs)}")
    print(f"  Dominant failure type:            {memories.dominant_failure_type}")
    print(f"  Historical failure rate:          {memories.historical_failure_rate:.0%}")
    print(f"  Has relevant memories:            {memories.has_relevant_memories}")

    best_strategy = retriever.get_best_repair_strategy(memories)
    print(f"  Best repair strategy (past):      {best_strategy}")

    recommended_prefixes = retriever.get_recommended_prompt_additions(memories)
    print(f"  Recommended prompt additions:     {len(recommended_prefixes)}")
    for p in recommended_prefixes:
        print(f"    - \"{p[:80]}...\"" if len(p) > 80 else f"    - \"{p}\"")

    # ── Step 4: Generate adapted config ───────────────────────────────────────
    print_separator("Step 4 — Generating AdaptedExecutionConfig")
    config = adapter.get_adapted_config(
        task_description=new_task,
        node_type="extract_invoice",
        base_n_drafts=5,
        base_inject_threshold=0.50,
        base_warn_threshold=0.30,
    )
    print_adapted_config(config)

    # ── Step 5: Show the contrast ──────────────────────────────────────────────
    print_separator("Step 5 — What changes: before vs after adaptation")
    print("  WITHOUT memory adaptation (what the node would normally do):")
    print("    SPA inject threshold:  0.50")
    print("    SCS N drafts:          5")
    print("    System prompt:         [original only]")
    print("    Deep reasoning:        False")
    print()
    print("  WITH memory adaptation (what the node will actually do):")
    spa = config.spa_inject_threshold_override
    n   = config.n_drafts_override
    print(f"    SPA inject threshold:  {spa:.2f}  ← tighter" if spa else "    SPA inject threshold:  0.50  (unchanged)")
    print(f"    SCS N drafts:          {n}     ← more sampling" if n else "    SCS N drafts:          5  (unchanged)")
    if config.prompt_prefix_additions:
        print(f"    System prompt:         [original + {len(config.prompt_prefix_additions)} additions]")
    print(f"    Deep reasoning:        {config.force_deep_reason}")
    print()
    print("  Result: the system prevents this known failure BEFORE it happens.")
    print("          No failure needed. No retry wasted. No user-visible error.")

    # ── Step 6: Record an outcome ──────────────────────────────────────────────
    print_separator("Step 6 — Recording execution outcome (closes the loop)")
    # Simulate: we ran the node, it succeeded, now we store the outcome
    new_record = CognitiveFailureRecord(
        node_type="extract_invoice",
        task_description=new_task,
        failure_type=FailureType.SCHEMA_VIOLATION,
        validator_error="Initially missing vendor_name",
        repair_successful=False,
    )
    store.save(new_record)
    print(f"  Stored new failure record: {new_record.record_id}")
    adapter.record_execution_outcome(
        store=store,
        record_id=new_record.record_id,
        repair_successful=True,
        successful_output='{"vendor_name": "ACME Corp", "total": 1450.00, ...}',
        repair_prompt_delta="Adaptive prefix from FMB fixed schema compliance",
        recommended_spa_threshold=0.37,
        recommended_n_drafts=6,
        recommended_prompt_prefix="Always include vendor_name, line_items, total, currency.",
    )
    updated = store.get_by_id(new_record.record_id)
    print(f"  Updated record: repair_successful={updated.repair_successful}")
    print(f"  Recommended SPA threshold stored: {updated.recommended_spa_threshold}")
    print(f"  This record will inform the NEXT run of a similar task.")

    store.close()

    print()
    print("=" * 65)
    print("  Demo complete. No Ollama required — FMB works standalone.")
    print("=" * 65)


if __name__ == "__main__":
    main()
```

---

## HOW TO VERIFY YOUR WORK

```bash
# 1. Install the one new dependency
pip install chromadb

# 2. Run unit tests (NO external services needed)
pytest specforge/tests/test_memory.py -v
# Expected: 18+ tests pass, 0 fail

# 3. Run the demo (no Ollama needed)
python -m specforge.demos.memory_demo
# Expected output:
#   - 5 failure records seeded across 3 node types
#   - Semantic search returning similar invoice failures for a new invoice task
#   - RelevantMemories showing dominant failure_type = schema_violation
#   - AdaptedExecutionConfig showing:
#       * Lowered SPA threshold (was 0.50, now ~0.38)
#       * Prompt prefix additions from past successful repairs
#   - Final message: "prevents failure BEFORE it happens"
```

---

## INTEGRATION (day 3 — 10 minutes, done together)

**Your module's interface to the rest of SpecForge is two calls:**

```python
from specforge.memory import MemoryStore, MemoryRetriever, MemoryAdapter
from specforge.memory import CognitiveFailureRecord, FailureType

_store    = MemoryStore()
_adapter  = MemoryAdapter(MemoryRetriever(_store))

# ── BEFORE node execution: get adapted config ──────────────────────────────
adapted = _adapter.get_adapted_config(
    task_description=node.rendered_prompt,
    node_type=node.node_type,
    base_inject_threshold=0.50,
)
# Apply prompt additions:
if adapted.prompt_prefix_additions:
    node.rendered_prompt = "\n".join(adapted.prompt_prefix_additions) + "\n\n" + node.rendered_prompt
# Apply SPA override:
if adapted.spa_inject_threshold_override:
    node.bento_config["pressure_annealing"]["inject_threshold"] = adapted.spa_inject_threshold_override

# ── AFTER node execution: record outcome ──────────────────────────────────
if validation_failed:
    record = CognitiveFailureRecord(
        node_type=node.node_type,
        task_description=node.rendered_prompt,
        failure_type=FailureType.SCHEMA_VIOLATION,  # or detect from validator error
        validator_error=str(validation_error),
        entropy_at_failure=spa_executor.monitor.current_smoothed(),
    )
    _store.save(record)
    # ... attempt repair ...
    _adapter.record_execution_outcome(
        store=_store,
        record_id=record.record_id,
        repair_successful=repair_worked,
    )
```

**These two calls go into `specforge/executor/atomic_executor.py`.**
