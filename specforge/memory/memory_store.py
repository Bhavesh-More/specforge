import sqlite3
import os
import uuid as _uuid
from typing import Optional
from pathlib import Path

import chromadb

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

        If chroma_path == ":memory:" or db_path == ":memory:", use EphemeralClient
        (in-memory, no disk) — ideal for testing.
        Otherwise use PersistentClient.
        """
        # ── SQLite setup ───────────────────────────────────────────────────────
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row   # enables dict-like access
        self._conn.executescript(self.SQLITE_SCHEMA)
        self._conn.commit()

        # ── ChromaDB setup ─────────────────────────────────────────────────────
        if chroma_path == ":memory:" or db_path == ":memory:":
            client = chromadb.EphemeralClient()
            # Each ephemeral store gets a unique collection name to prevent
            # cross-test state leakage when EphemeralClient is process-global.
            effective_collection = f"{collection_name}_{_uuid.uuid4().hex[:8]}"
        else:
            Path(chroma_path).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=chroma_path)
            effective_collection = collection_name

        self._collection = client.get_or_create_collection(
            name=effective_collection,
            # ChromaDB uses its default embedding function (all-MiniLM-L6-v2)
            # Fast, local, and sufficient for our use case.
        )

    def save(self, record: CognitiveFailureRecord) -> None:
        """
        Save a record to BOTH SQLite and ChromaDB.

        If a record with the same record_id already exists, replace it (upsert).
        """
        # ── SQLite ─────────────────────────────────────────────────────────────
        d = record.to_dict()
        values = [d[col] for col in self.COLUMNS]
        placeholders = ", ".join(["?"] * len(self.COLUMNS))
        cols = ", ".join(self.COLUMNS)
        self._conn.execute(
            f"INSERT OR REPLACE INTO cognitive_failures ({cols}) VALUES ({placeholders})",
            values
        )
        self._conn.commit()

        # ── ChromaDB ───────────────────────────────────────────────────────────
        doc = record.to_chroma_document()
        self._collection.upsert(
            ids=[doc["id"]],
            documents=[doc["document"]],
            metadatas=[doc["metadata"]]
        )

    def get_by_id(self, record_id: str) -> Optional[CognitiveFailureRecord]:
        """
        Retrieve a single record by UUID.
        Returns None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM cognitive_failures WHERE record_id = ?",
            (record_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return CognitiveFailureRecord.from_dict(dict(row))

    def get_by_node_type(
        self,
        node_type: str,
        limit: int = 20,
        repair_successful_only: bool = False,
    ) -> list[CognitiveFailureRecord]:
        """
        Get recent failure records for a specific node type.

        Optionally filter to only successfully repaired records.
        Returns empty list if no records found.
        """
        if repair_successful_only:
            sql = (
                "SELECT * FROM cognitive_failures "
                "WHERE node_type = ? AND repair_successful = 1 "
                "ORDER BY created_at DESC LIMIT ?"
            )
        else:
            sql = (
                "SELECT * FROM cognitive_failures "
                "WHERE node_type = ? "
                "ORDER BY created_at DESC LIMIT ?"
            )
        cursor = self._conn.execute(sql, (node_type, limit))
        rows = cursor.fetchall()
        return [CognitiveFailureRecord.from_dict(dict(row)) for row in rows]

    def get_failure_count_by_node_type(self) -> dict[str, int]:
        """
        Return a dict mapping each node_type to its total failure count.

        Returns: {"extract_invoice": 12, "reason_causal": 5, ...}
        Returns empty dict if table is empty.
        """
        cursor = self._conn.execute(
            "SELECT node_type, COUNT(*) as cnt "
            "FROM cognitive_failures "
            "GROUP BY node_type "
            "ORDER BY cnt DESC"
        )
        rows = cursor.fetchall()
        return {row["node_type"]: row["cnt"] for row in rows}

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

        Silently does nothing if record_id does not exist.
        """
        # ── SQLite UPDATE ──────────────────────────────────────────────────────
        self._conn.execute(
            """
            UPDATE cognitive_failures
            SET repair_successful = ?,
                successful_output = ?,
                repair_prompt_delta = ?,
                recommended_spa_threshold = ?,
                recommended_n_drafts = ?,
                recommended_prompt_prefix = ?
            WHERE record_id = ?
            """,
            (
                int(repair_successful),
                successful_output,
                repair_prompt_delta,
                recommended_spa_threshold,
                recommended_n_drafts,
                recommended_prompt_prefix,
                record_id,
            )
        )
        self._conn.commit()

        # ── ChromaDB metadata update ───────────────────────────────────────────
        # Only update if the record exists in ChromaDB (avoid error on missing id)
        try:
            self._collection.update(
                ids=[record_id],
                metadatas=[{
                    "repair_successful": str(repair_successful),
                    "recommended_spa_threshold": str(recommended_spa_threshold or ""),
                    "recommended_n_drafts": str(recommended_n_drafts or ""),
                    "recommended_prompt_prefix": recommended_prompt_prefix,
                }]
            )
        except Exception:
            # If the record doesn't exist in ChromaDB, silently ignore
            pass

    def semantic_search(
        self,
        query_text: str,
        node_type_filter: Optional[str] = None,
        n_results: int = 5,
    ) -> list[tuple[CognitiveFailureRecord, float]]:
        """
        Search for similar past failures using ChromaDB's semantic search.

        ChromaDB returns L2 distances (lower = more similar).
        Converts to similarity score: similarity = 1.0 / (1.0 + distance)
        This maps distance 0 → similarity 1.0, distance ∞ → similarity 0.0.

        Returns sorted by similarity descending.
        Returns empty list if collection is empty or query_text is empty.
        """
        if not query_text or self._collection.count() == 0:
            return []

        count = self._collection.count()
        safe_n = min(n_results, count)

        query_kwargs: dict = dict(
            query_texts=[query_text],
            n_results=safe_n,
            include=["distances", "metadatas"],
        )
        # Only add `where` if filtering — passing where=None causes ChromaDB issues
        if node_type_filter:
            query_kwargs["where"] = {"node_type": node_type_filter}

        results = self._collection.query(**query_kwargs)

        output: list[tuple[CognitiveFailureRecord, float]] = []
        ids = results["ids"][0]
        distances = results["distances"][0]

        for record_id, distance in zip(ids, distances):
            similarity = 1.0 / (1.0 + distance)
            record = self.get_by_id(record_id)
            if record is not None:
                output.append((record, similarity))

        # Sort by similarity descending
        output.sort(key=lambda x: x[1], reverse=True)
        return output

    def close(self) -> None:
        """
        Close the SQLite connection.
        ChromaDB client does not need explicit closing.
        """
        if hasattr(self, "_conn") and self._conn:
            self._conn.close()
