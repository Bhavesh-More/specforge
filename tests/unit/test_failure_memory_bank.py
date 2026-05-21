import pytest

from specforge.memory import (
    CognitiveFailureRecord,
    FailureType,
    MemoryAdapter,
    MemoryRetriever,
    MemoryStore,
)


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(db_path=str(tmp_path / "fmb.sqlite3"), chroma_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def sample_record():
    return CognitiveFailureRecord(
        node_type="extract_invoice",
        task_description="Extract line items totals and vendor name from invoice",
        model_used="llama3:8b",
        failure_type=FailureType.SCHEMA_VIOLATION,
        validator_error='Required field "vendor_name" is missing',
        failed_output='{"line_items": [], "total": 450.0}',
        repair_attempted=True,
        repair_strategy_used="strict_json_prompt",
        repair_successful=True,
        recommended_prompt_prefix="Always include vendor_name, line_items, total, currency.",
        recommended_spa_threshold=0.38,
        recommended_n_drafts=7,
    )


def test_record_roundtrip_and_chroma_document(sample_record):
    restored = CognitiveFailureRecord.from_dict(sample_record.to_dict())

    assert restored.failure_type == FailureType.SCHEMA_VIOLATION
    assert restored.repair_successful is True
    doc = restored.to_chroma_document()
    assert doc["id"] == sample_record.record_id
    assert doc["document"] == sample_record.task_description
    assert all(value is not None for value in doc["metadata"].values())


def test_store_save_retrieve_and_update(store, sample_record):
    store.save(sample_record)

    retrieved = store.get_by_id(sample_record.record_id)
    assert retrieved is not None
    assert retrieved.failure_type == FailureType.SCHEMA_VIOLATION

    store.update_repair_outcome(
        sample_record.record_id,
        repair_successful=True,
        successful_output="valid output",
        recommended_spa_threshold=0.35,
        recommended_n_drafts=6,
    )
    updated = store.get_by_id(sample_record.record_id)
    assert updated is not None
    assert updated.successful_output == "valid output"
    assert updated.recommended_spa_threshold == pytest.approx(0.35)
    assert updated.recommended_n_drafts == 6


def test_semantic_search_uses_lexical_fallback_without_chromadb(store):
    store.save(
        CognitiveFailureRecord(
            node_type="extract_invoice",
            task_description="Extract invoice vendor line items and totals",
            failure_type=FailureType.SCHEMA_VIOLATION,
        )
    )
    store.save(
        CognitiveFailureRecord(
            node_type="reason_causal",
            task_description="Explain payment gateway retry race condition",
            failure_type=FailureType.PREMATURE_CONCLUSION,
        )
    )

    results = store.semantic_search(
        "extract invoice totals", node_type_filter="extract_invoice"
    )

    assert results
    assert results[0][0].node_type == "extract_invoice"


def test_retriever_detects_dominant_failure_type(store):
    for i in range(4):
        store.save(
            CognitiveFailureRecord(
                node_type="extract_invoice",
                task_description=f"extract invoice vendor totals task {i}",
                failure_type=FailureType.SCHEMA_VIOLATION,
                repair_successful=True,
                recommended_prompt_prefix="Include all required fields.",
            )
        )

    memories = MemoryRetriever(store).retrieve_for_task(
        "extract invoice vendor totals", "extract_invoice"
    )

    assert memories.has_relevant_memories
    assert memories.dominant_failure_type == FailureType.SCHEMA_VIOLATION
    assert len(memories.successful_repairs) >= 2


def test_adapter_applies_schema_violation_adaptation(store):
    for i in range(4):
        store.save(
            CognitiveFailureRecord(
                node_type="extract_invoice",
                task_description=f"extract invoice required fields vendor total {i}",
                failure_type=FailureType.SCHEMA_VIOLATION,
                repair_successful=True,
                recommended_prompt_prefix="Always include vendor_name.",
                recommended_spa_threshold=0.38,
            )
        )

    adapter = MemoryAdapter(MemoryRetriever(store))
    config = adapter.get_adapted_config(
        "extract invoice vendor total",
        "extract_invoice",
        base_inject_threshold=0.50,
    )

    assert config.memories_used >= 2
    assert config.spa_inject_threshold_override == pytest.approx(0.38)
    assert any("schema" in p.lower() for p in config.prompt_prefix_additions)
    assert "Always include vendor_name." in config.prompt_prefix_additions


def test_adapter_forces_deep_reason_for_premature_conclusion(store):
    for i in range(4):
        store.save(
            CognitiveFailureRecord(
                node_type="reason_causal",
                task_description=f"reason causal chain payment retry {i}",
                failure_type=FailureType.PREMATURE_CONCLUSION,
                repair_successful=True,
            )
        )

    config = MemoryAdapter(MemoryRetriever(store)).get_adapted_config(
        "reason causal chain payment retry",
        "reason_causal",
    )

    assert config.memories_used >= 2
    assert config.force_deep_reason is True
