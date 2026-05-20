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
    line = "-" * 65
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
