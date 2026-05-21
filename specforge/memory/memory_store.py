"""Dual-store persistence for the Failure Memory Bank."""

import re
import sqlite3
from pathlib import Path
from typing import Optional

from .failure_record import CognitiveFailureRecord

try:  # ChromaDB is optional so SpecForge still works without extra installs.
    import chromadb
except Exception:  # pragma: no cover - depends on optional environment package
    chromadb = None


TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _lexical_similarity(left: str, right: str) -> float:
    left_tokens = {_normalise_token(token) for token in TOKEN_RE.findall(left.lower())}
    right_tokens = {_normalise_token(token) for token in TOKEN_RE.findall(right.lower())}
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    jaccard = overlap / len(left_tokens | right_tokens)
    query_coverage = overlap / len(left_tokens)
    return max(jaccard, query_coverage)


def _normalise_token(token: str) -> str:
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


class MemoryStore:
    """SQLite plus optional ChromaDB persistence for failure records."""

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

    COLUMNS = [
        "record_id",
        "created_at",
        "node_type",
        "task_description",
        "model_used",
        "failure_type",
        "validator_error",
        "failed_output",
        "entropy_at_failure",
        "repair_attempted",
        "repair_strategy_used",
        "repair_successful",
        "successful_output",
        "repair_prompt_delta",
        "recommended_spa_threshold",
        "recommended_n_drafts",
        "recommended_prompt_prefix",
    ]

    def __init__(
        self,
        db_path: str = "specforge_memory.db",
        chroma_path: str = "./chroma_memory",
        collection_name: str = "cognitive_failures",
    ):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SQLITE_SCHEMA)
        self._conn.commit()

        self._collection = None
        if chromadb is not None:
            try:
                if chroma_path == ":memory:" or db_path == ":memory:":
                    client = chromadb.EphemeralClient()
                else:
                    Path(chroma_path).mkdir(parents=True, exist_ok=True)
                    client = chromadb.PersistentClient(path=chroma_path)
                self._collection = client.get_or_create_collection(
                    name=collection_name
                )
            except Exception:
                self._collection = None

    def save(self, record: CognitiveFailureRecord) -> None:
        """Save a record to SQLite and optional ChromaDB."""
        d = record.to_dict()
        values = [d[col] for col in self.COLUMNS]
        placeholders = ", ".join(["?"] * len(self.COLUMNS))
        cols = ", ".join(self.COLUMNS)
        self._conn.execute(
            f"INSERT OR REPLACE INTO cognitive_failures ({cols}) VALUES ({placeholders})",
            values,
        )
        self._conn.commit()

        if self._collection is not None and record.task_description.strip():
            doc = record.to_chroma_document()
            self._collection.upsert(
                ids=[doc["id"]],
                documents=[doc["document"]],
                metadatas=[doc["metadata"]],
            )

    def get_by_id(self, record_id: str) -> Optional[CognitiveFailureRecord]:
        """Retrieve one record by UUID."""
        row = self._conn.execute(
            "SELECT * FROM cognitive_failures WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return CognitiveFailureRecord.from_dict(dict(row))

    def get_by_node_type(
        self,
        node_type: str,
        limit: int = 20,
        repair_successful_only: bool = False,
    ) -> list[CognitiveFailureRecord]:
        """Get recent failure records for one node type."""
        sql = "SELECT * FROM cognitive_failures WHERE node_type = ?"
        params: list[object] = [node_type]
        if repair_successful_only:
            sql += " AND repair_successful = 1"
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [CognitiveFailureRecord.from_dict(dict(row)) for row in rows]

    def get_failure_count_by_node_type(self) -> dict[str, int]:
        """Return total failure count per node type."""
        rows = self._conn.execute(
            """
            SELECT node_type, COUNT(*) AS cnt
            FROM cognitive_failures
            GROUP BY node_type
            ORDER BY cnt DESC
            """
        ).fetchall()
        return {row["node_type"]: int(row["cnt"]) for row in rows}

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
        """Update a record after a repair attempt completes."""
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
                successful_output[:500],
                repair_prompt_delta,
                recommended_spa_threshold,
                recommended_n_drafts,
                recommended_prompt_prefix,
                record_id,
            ),
        )
        self._conn.commit()

        if self._collection is not None:
            try:
                self._collection.update(
                    ids=[record_id],
                    metadatas=[
                        {
                            "repair_successful": str(repair_successful),
                            "recommended_spa_threshold": str(
                                recommended_spa_threshold or ""
                            ),
                            "recommended_n_drafts": str(recommended_n_drafts or ""),
                            "recommended_prompt_prefix": recommended_prompt_prefix,
                        }
                    ],
                )
            except Exception:
                pass

    def semantic_search(
        self,
        query_text: str,
        node_type_filter: Optional[str] = None,
        n_results: int = 5,
    ) -> list[tuple[CognitiveFailureRecord, float]]:
        """Search for similar past failures."""
        if not query_text.strip():
            return []

        if self._collection is not None:
            try:
                count = self._collection.count()
                if count == 0:
                    return []
                where_filter = {"node_type": node_type_filter} if node_type_filter else None
                results = self._collection.query(
                    query_texts=[query_text],
                    n_results=min(n_results, count),
                    where=where_filter,
                    include=["distances", "metadatas"],
                )
                found: list[tuple[CognitiveFailureRecord, float]] = []
                for record_id, distance in zip(
                    results.get("ids", [[]])[0],
                    results.get("distances", [[]])[0],
                ):
                    record = self.get_by_id(record_id)
                    if record is not None:
                        found.append((record, 1.0 / (1.0 + float(distance))))
                return sorted(found, key=lambda item: item[1], reverse=True)
            except Exception:
                pass

        return self._lexical_search(query_text, node_type_filter, n_results)

    def _lexical_search(
        self,
        query_text: str,
        node_type_filter: Optional[str],
        n_results: int,
    ) -> list[tuple[CognitiveFailureRecord, float]]:
        sql = "SELECT * FROM cognitive_failures"
        params: list[object] = []
        if node_type_filter:
            sql += " WHERE node_type = ?"
            params.append(node_type_filter)
        rows = self._conn.execute(sql, params).fetchall()
        scored: list[tuple[CognitiveFailureRecord, float]] = []
        for row in rows:
            record = CognitiveFailureRecord.from_dict(dict(row))
            score = _lexical_similarity(query_text, record.task_description)
            if score > 0:
                scored.append((record, score))
        return sorted(scored, key=lambda item: item[1], reverse=True)[:n_results]

    def close(self) -> None:
        """Close SQLite connection."""
        if getattr(self, "_conn", None) is not None:
            self._conn.close()
