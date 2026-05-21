from pathlib import Path

import pytest

from src.quality.memory_bank import QualityMemoryBank
from src.quality.models import MemoryRecord


@pytest.mark.asyncio
async def test_memory_bank_add_and_retrieve(tmp_path: Path):
    bank = QualityMemoryBank(tmp_path / "quality.sqlite3")
    await bank.initialize()
    await bank.add_record(
        MemoryRecord(
            id="rec-1",
            template_id="bug_report",
            template_name="Bug Report",
            node_id="root_cause",
            node_type="standard",
            run_id="run-1",
            task_text="websocket reconnect collaborative editor corruption",
            input_hash="hash",
            record_type="success",
            content={"advice": "check reconnect ordering"},
            quality_score=0.9,
            tags=["test"],
            created_at="2026-01-01T00:00:00+00:00",
        )
    )

    results = await bank.retrieve(
        template_id="bug_report",
        task_text="collaborative editor websocket reconnect causes corruption",
        node_id="root_cause",
        node_type="standard",
    )

    assert len(results) == 1
    assert results[0].record.id == "rec-1"
    assert results[0].similarity > 0.2


@pytest.mark.asyncio
async def test_memory_bank_excludes_unrelated_records(tmp_path: Path):
    bank = QualityMemoryBank(tmp_path / "quality.sqlite3")
    await bank.initialize()
    await bank.add_record(
        MemoryRecord(
            id="rec-1",
            template_id="bug_report",
            node_id="root_cause",
            node_type="standard",
            task_text="invoice tax extraction totals",
            input_hash="hash",
            record_type="success",
            content={"advice": "currency parsing"},
            tags=[],
            created_at="2026-01-01T00:00:00+00:00",
        )
    )

    results = await bank.retrieve(
        template_id="bug_report",
        task_text="websocket reconnect cursor desync",
        min_similarity=0.5,
    )

    assert results == []
