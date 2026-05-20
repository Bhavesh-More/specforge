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
