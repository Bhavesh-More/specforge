"""Persistent local memory for template-specific quality improvement."""

import asyncio
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.quality.models import MemoryRecord, RetrievedMemory


TOKEN_RE = re.compile(r"[a-z0-9_]+")


def stable_input_hash(value: Any) -> str:
    """Return a deterministic hash for user input or task payload."""
    payload = json.dumps(value, sort_keys=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _jaccard(left: str, right: str) -> float:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _compact_json(value: Any, max_chars: int = 6000) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text[:max_chars]


class QualityMemoryBank:
    """SQLite-backed local memory for previous SpecForge runs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def initialize(self) -> None:
        """Create SQLite tables if missing."""
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quality_memory (
                  id TEXT PRIMARY KEY,
                  template_id TEXT NOT NULL,
                  template_name TEXT,
                  node_id TEXT,
                  node_type TEXT,
                  run_id TEXT,
                  task_text TEXT NOT NULL,
                  input_hash TEXT NOT NULL,
                  record_type TEXT NOT NULL,
                  content_json TEXT NOT NULL,
                  quality_score REAL,
                  tags_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quality_memory_template "
                "ON quality_memory(template_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quality_memory_node "
                "ON quality_memory(template_id, node_id)"
            )

    async def add_record(self, record: MemoryRecord) -> None:
        """Insert a memory record."""
        await asyncio.to_thread(self._add_record_sync, record)

    def _add_record_sync(self, record: MemoryRecord) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_memory (
                    id, template_id, template_name, node_id, node_type, run_id,
                    task_text, input_hash, record_type, content_json,
                    quality_score, tags_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.template_id,
                    record.template_name,
                    record.node_id,
                    record.node_type,
                    record.run_id,
                    record.task_text,
                    record.input_hash,
                    record.record_type,
                    json.dumps(record.content, ensure_ascii=False, default=str),
                    record.quality_score,
                    json.dumps(record.tags, ensure_ascii=False),
                    record.created_at,
                ),
            )

    async def retrieve(
        self,
        template_id: str,
        task_text: str,
        node_id: str | None = None,
        node_type: str | None = None,
        limit: int = 5,
        min_similarity: float = 0.12,
    ) -> list[RetrievedMemory]:
        """Return the most relevant memories for this template/node/task."""
        rows = await asyncio.to_thread(self._load_candidate_rows, template_id)
        scored: list[RetrievedMemory] = []

        for row in rows:
            record = self._record_from_row(row)
            similarity = _jaccard(task_text, record.task_text)
            reasons: list[str] = []

            if node_id and record.node_id == node_id:
                similarity += 0.12
                reasons.append("same node")
            if node_type and record.node_type == node_type:
                similarity += 0.08
                reasons.append("same node type")
            if record.record_type in {"teacher_critique", "domain_insight"}:
                similarity += 0.03
                reasons.append("teacher/domain guidance")

            similarity = min(similarity, 1.0)
            if similarity >= min_similarity:
                scored.append(
                    RetrievedMemory(
                        record=record,
                        similarity=similarity,
                        reason=", ".join(reasons) or "lexical task overlap",
                    )
                )

        return sorted(scored, key=lambda item: item.similarity, reverse=True)[:limit]

    def _load_candidate_rows(self, template_id: str) -> list[sqlite3.Row]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM quality_memory
                WHERE template_id = ?
                ORDER BY created_at DESC
                LIMIT 500
                """,
                (template_id,),
            )
            return list(cursor.fetchall())

    def _record_from_row(self, row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            template_id=row["template_id"],
            template_name=row["template_name"],
            node_id=row["node_id"],
            node_type=row["node_type"],
            run_id=row["run_id"],
            task_text=row["task_text"],
            input_hash=row["input_hash"],
            record_type=row["record_type"],
            content=json.loads(row["content_json"]),
            quality_score=row["quality_score"],
            tags=json.loads(row["tags_json"]),
            created_at=row["created_at"],
        )

    async def record_node_success(
        self,
        *,
        template_id: str,
        template_name: str,
        run_id: str,
        node_id: str,
        node_type: str,
        task_text: str,
        input_hash: str,
        parsed_output: dict[str, Any] | None,
        raw_output: str,
        quality_score: float | None = None,
    ) -> None:
        """Store a successful node result."""
        await self.add_record(
            MemoryRecord(
                id=str(uuid.uuid4()),
                template_id=template_id,
                template_name=template_name,
                node_id=node_id,
                node_type=node_type,
                run_id=run_id,
                task_text=task_text,
                input_hash=input_hash,
                record_type="success",
                content={
                    "parsed_output": parsed_output,
                    "raw_output_preview": raw_output[:3000],
                },
                quality_score=quality_score,
                tags=["node_success", node_type],
                created_at=_now_iso(),
            )
        )

    async def record_node_failure(
        self,
        *,
        template_id: str,
        template_name: str,
        run_id: str,
        node_id: str,
        node_type: str,
        task_text: str,
        input_hash: str,
        raw_output: str,
        error: str,
    ) -> None:
        """Store a failed node result."""
        await self.add_record(
            MemoryRecord(
                id=str(uuid.uuid4()),
                template_id=template_id,
                template_name=template_name,
                node_id=node_id,
                node_type=node_type,
                run_id=run_id,
                task_text=task_text,
                input_hash=input_hash,
                record_type="failure",
                content={"raw_output_preview": raw_output[:3000], "error": error},
                tags=["node_failure", node_type],
                created_at=_now_iso(),
            )
        )

    async def record_teacher_critique(
        self,
        *,
        template_id: str,
        template_name: str,
        run_id: str,
        node_id: str,
        node_type: str,
        task_text: str,
        input_hash: str,
        critique: dict[str, Any],
        quality_score: float | None,
    ) -> None:
        """Store teacher critique for reuse on similar tasks."""
        await self.add_record(
            MemoryRecord(
                id=str(uuid.uuid4()),
                template_id=template_id,
                template_name=template_name,
                node_id=node_id,
                node_type=node_type,
                run_id=run_id,
                task_text=task_text,
                input_hash=input_hash,
                record_type="teacher_critique",
                content=critique,
                quality_score=quality_score,
                tags=["teacher_critique", node_type],
                created_at=_now_iso(),
            )
        )

    async def record_final_output(
        self,
        *,
        template_id: str,
        template_name: str,
        run_id: str,
        task_text: str,
        input_hash: str,
        final_output: dict[str, Any],
        quality_score: float | None,
    ) -> None:
        """Store final run output."""
        await self.add_record(
            MemoryRecord(
                id=str(uuid.uuid4()),
                template_id=template_id,
                template_name=template_name,
                run_id=run_id,
                task_text=task_text,
                input_hash=input_hash,
                record_type="final_output",
                content={"final_output_preview": _compact_json(final_output)},
                quality_score=quality_score,
                tags=["final_output"],
                created_at=_now_iso(),
            )
        )
