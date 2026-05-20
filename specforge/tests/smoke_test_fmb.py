"""
FMB Smoke Test — run with: python -m specforge.tests.smoke_test_fmb
Exit 0 = all pass. Exit 1 = failures detected.
"""
import sys, traceback, tempfile, os

GREEN = "\033[92m"; RED = "\033[91m"; CYAN = "\033[96m"; RESET = "\033[0m"; BOLD = "\033[1m"

_passed = 0; _failed = 0; _log = []

def check(name, fn):
    global _passed, _failed
    try:
        fn()
        print(f"  PASS  {name}")
        _log.append((name, True, "")); _passed += 1
    except Exception as e:
        tb = traceback.format_exc().strip().splitlines()[-1]
        print(f"  FAIL  {name}\n        {tb}")
        _log.append((name, False, str(e))); _failed += 1

def ok(cond, msg=""):
    if not cond: raise AssertionError(msg or "condition false")

def section(t):
    print(f"\n{CYAN}{BOLD}[ {t} ]{RESET}\n  {'-'*60}")

# ── helpers defined BEFORE run() ──────────────────────────────────────────────

def h_roundtrip(CFR, FT, make):
    r = make(); d = r.to_dict(); restored = CFR.from_dict(d)
    ok(restored.record_id == r.record_id)
    ok(restored.failure_type == FT.SCHEMA_VIOLATION)
    ok(restored.repair_successful is True)
    ok(restored.recommended_spa_threshold == 0.38)

def h_upsert(store, record):
    record.validator_error = "smoke-upsert-check"
    store.save(record)
    ok(store.get_by_id(record.record_id).validator_error == "smoke-upsert-check")

def h_update(store, rec):
    store.update_repair_outcome(rec.record_id, True,
        successful_output="ok", recommended_spa_threshold=0.35, recommended_n_drafts=7)
    u = store.get_by_id(rec.record_id)
    ok(u.repair_successful is True)
    ok(u.recommended_spa_threshold == 0.35)
    ok(u.recommended_n_drafts == 7)

def h_search_sorted(store):
    r = store.semantic_search("extract invoice line items", n_results=3)
    ok(len(r) > 0, "no results")
    scores = [s for _, s in r]
    ok(scores == sorted(scores, reverse=True), f"not sorted: {scores}")

def h_search_filter(store):
    r = store.semantic_search("invoice", node_type_filter="reason_causal", n_results=5)
    for rec, _ in r:
        ok(rec.node_type == "reason_causal", f"got {rec.node_type}")

def h_search_relevance(store):
    r = store.semantic_search("extract invoice totals and vendor name", n_results=3)
    if r: ok(r[0][0].node_type == "extract_invoice", f"top={r[0][0].node_type}")

def h_scores_range(store):
    r = store.semantic_search("invoice extraction", n_results=3)
    for _, s in r: ok(0 < s <= 1.0, f"score={s}")

def h_schema_adapt(adapter):
    cfg = adapter.get_adapted_config("extract invoice data", "extract_invoice")
    if cfg.memories_used >= 2:
        ok(len(cfg.prompt_prefix_additions) > 0)

def h_outcome(store, adapter, CFR, FT):
    r = CFR(node_type="extract_invoice",
            task_description="Extract billing info from invoice",
            failure_type=FT.SCHEMA_VIOLATION, repair_successful=False)
    store.save(r)
    adapter.record_execution_outcome(store=store, record_id=r.record_id,
        repair_successful=True, successful_output='{"vendor":"ACME"}',
        recommended_spa_threshold=0.37, recommended_n_drafts=6,
        recommended_prompt_prefix="Include vendor_name.")
    u = store.get_by_id(r.record_id)
    ok(u.repair_successful is True)
    ok(u.recommended_spa_threshold == 0.37)

def h_persistence(MS, CFR, FT):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, "smoke.db")
        ch = os.path.join(tmp, "chroma")
        r = CFR(node_type="persist_node",
                task_description="Persistence smoke test",
                failure_type=FT.UNKNOWN)
        rid = r.record_id
        s1 = MS(db_path=db, chroma_path=ch); s1.save(r); s1.close()
        s2 = MS(db_path=db, chroma_path=ch)
        f = s2.get_by_id(rid)
        s2.close()  # close before tempdir cleanup to release Windows file locks
        ok(f is not None, "record lost after reopen")
        ok(f.node_type == "persist_node")

def h_full_loop(MS, MR, MA, CFR, FT):
    s = MS(db_path=":memory:", chroma_path=":memory:")
    ret = MR(s); ada = MA(ret)
    cfg0 = ada.get_adapted_config("generate monthly report", "report_gen")
    ok(cfg0.memories_used == 0)
    for i in range(3):
        s.save(CFR(node_type="report_gen",
                   task_description=f"Generate monthly sales report Q{i+1}",
                   failure_type=FT.PREMATURE_CONCLUSION, repair_successful=True,
                   recommended_prompt_prefix="Include 12 months with YoY."))
    cfg1 = ada.get_adapted_config("generate monthly sales report summary", "report_gen")
    ok(cfg1.memories_used >= 1, f"got {cfg1.memories_used}")
    new = CFR(node_type="report_gen",
              task_description="Generate quarterly sales report",
              failure_type=FT.PREMATURE_CONCLUSION, repair_successful=False)
    s.save(new)
    ada.record_execution_outcome(store=s, record_id=new.record_id,
        repair_successful=True, successful_output="Full report...")
    ok(s.get_by_id(new.record_id).repair_successful is True)
    s.close()

# ── main ──────────────────────────────────────────────────────────────────────

def run():
    print(f"\n{BOLD}{'='*65}{RESET}")
    print(f"{BOLD}  SpecForge FMB -- Smoke Test{RESET}")
    print(f"{BOLD}{'='*65}{RESET}")

    # 1. Imports
    section("1. Package Imports")
    check("Import failure_record module", lambda: __import__(
        "specforge.memory.failure_record", fromlist=["CognitiveFailureRecord"]))
    check("Import memory_store module", lambda: __import__(
        "specforge.memory.memory_store", fromlist=["MemoryStore"]))
    check("Import memory_retriever module", lambda: __import__(
        "specforge.memory.memory_retriever", fromlist=["MemoryRetriever"]))
    check("Import memory_adapter module", lambda: __import__(
        "specforge.memory.memory_adapter", fromlist=["MemoryAdapter"]))

    def chk_exports():
        import specforge.memory as m
        for sym in ["CognitiveFailureRecord","FailureType","MemoryStore",
                    "MemoryRetriever","RelevantMemories","MemoryAdapter","AdaptedExecutionConfig"]:
            ok(hasattr(m, sym), f"Missing: {sym}")
    check("__init__.py exports all 7 symbols", chk_exports)

    from specforge.memory import (
        CognitiveFailureRecord as CFR, FailureType as FT,
        MemoryStore as MS, MemoryRetriever as MR, RelevantMemories,
        MemoryAdapter as MA, AdaptedExecutionConfig as AEC,
    )

    def make():
        return CFR(node_type="extract_invoice",
                   task_description="Extract all line items and totals from invoice",
                   model_used="llama3:8b", failure_type=FT.SCHEMA_VIOLATION,
                   validator_error="Missing field: vendor_name", entropy_at_failure=0.52,
                   repair_attempted=True, repair_strategy_used="strict_json_prompt",
                   repair_successful=True, recommended_prompt_prefix="Always include vendor_name.",
                   recommended_spa_threshold=0.38, recommended_n_drafts=6)

    # 2. CognitiveFailureRecord
    section("2. CognitiveFailureRecord")
    check("UUID record_id auto-generated (len=36)",
          lambda: ok(len(CFR().record_id) == 36))
    check("ISO created_at contains 'T'",
          lambda: ok("T" in CFR().created_at))
    check("FailureType has 8 variants",
          lambda: ok(len(FT) == 8, f"got {len(FT)}"))
    check("to_dict() failure_type is string",
          lambda: ok(isinstance(make().to_dict()["failure_type"], str)))
    check("to_dict() failure_type value == 'schema_violation'",
          lambda: ok(make().to_dict()["failure_type"] == "schema_violation"))
    check("to_dict() repair_attempted=1, repair_successful=1",
          lambda: ok(make().to_dict()["repair_attempted"] == 1 and
                     make().to_dict()["repair_successful"] == 1))
    check("from_dict() roundtrip preserves all fields",
          lambda: h_roundtrip(CFR, FT, make))
    check("to_chroma_document() has id/document/metadata",
          lambda: ok(all(k in make().to_chroma_document() for k in ["id","document","metadata"])))
    check("to_chroma_document() document == task_description",
          lambda: ok(make().to_chroma_document()["document"] == make().task_description))
    check("to_chroma_document() no None metadata values",
          lambda: ok(all(v is not None
                         for v in CFR().to_chroma_document()["metadata"].values())))

    # 3. MemoryStore — persistence
    section("3. MemoryStore -- Core Persistence")
    store = MS(db_path=":memory:", chroma_path=":memory:")
    record = make()
    check("save() succeeds without error",
          lambda: store.save(record))
    check("get_by_id() retrieves saved record",
          lambda: ok(store.get_by_id(record.record_id) is not None))
    check("get_by_id() returns None for unknown id",
          lambda: ok(store.get_by_id("no-such-id") is None))
    check("get_by_id() preserves FailureType enum",
          lambda: ok(store.get_by_id(record.record_id).failure_type == FT.SCHEMA_VIOLATION))
    check("get_by_id() preserves repair_successful=True",
          lambda: ok(store.get_by_id(record.record_id).repair_successful is True))

    rec2 = CFR(node_type="extract_invoice",
               task_description="Parse invoice PDF and return JSON",
               failure_type=FT.SCHEMA_VIOLATION, repair_successful=False)
    rec3 = CFR(node_type="reason_causal",
               task_description="Explain causes of revenue decline Q3",
               failure_type=FT.HALLUCINATION_DRIFT, repair_successful=True)
    store.save(rec2); store.save(rec3)

    check("get_by_node_type() returns only matching node",
          lambda: ok(len(store.get_by_node_type("extract_invoice")) == 2))
    check("get_by_node_type(repair_successful_only) returns 1 record",
          lambda: ok(len(store.get_by_node_type("extract_invoice", repair_successful_only=True)) == 1))
    check("get_by_node_type() returns [] for unknown node",
          lambda: ok(store.get_by_node_type("nonexistent") == []))
    check("get_failure_count_by_node_type() counts correctly",
          lambda: ok(store.get_failure_count_by_node_type()["extract_invoice"] == 2))
    check("save() upserts on duplicate record_id",
          lambda: h_upsert(store, record))
    check("update_repair_outcome() persists changes",
          lambda: h_update(store, rec2))

    # 4. Semantic Search
    section("4. MemoryStore -- Semantic Search (ChromaDB)")
    empty = MS(db_path=":memory:", chroma_path=":memory:")
    check("semantic_search() returns [] on empty store",
          lambda: ok(empty.semantic_search("invoice task") == []))
    check("semantic_search() returns [] for empty query",
          lambda: ok(store.semantic_search("") == []))
    check("results sorted by similarity descending",
          lambda: h_search_sorted(store))
    check("node_type_filter returns only matching nodes",
          lambda: h_search_filter(store))
    check("top result matches query domain",
          lambda: h_search_relevance(store))
    check("all similarity scores in (0, 1]",
          lambda: h_scores_range(store))
    empty.close()

    # 5. MemoryRetriever
    section("5. MemoryRetriever")
    retriever = MR(store)
    check("retrieve_for_task() returns RelevantMemories",
          lambda: ok(isinstance(
              retriever.retrieve_for_task("extract invoice data", "extract_invoice"),
              RelevantMemories)))
    check("has_relevant_memories=True for known task type",
          lambda: ok(retriever.retrieve_for_task(
              "extract invoice line items", "extract_invoice").has_relevant_memories))
    check("has_relevant_memories=False for novel task type",
          lambda: ok(not retriever.retrieve_for_task(
              "quantum entanglement collapse", "novel_node_xyz").has_relevant_memories))
    check("all similar_failures above SIMILARITY_THRESHOLD",
          lambda: ok(all(
              s >= 0.60 for _, s in retriever.retrieve_for_task(
                  "extract invoice data", "extract_invoice").similar_failures)))
    check("successful_repairs all have repair_successful=True",
          lambda: ok(all(
              r.repair_successful for r in retriever.retrieve_for_task(
                  "extract invoice data", "extract_invoice").successful_repairs)))
    check("historical_failure_rate in [0.0, 1.0]",
          lambda: ok(0.0 <= retriever.retrieve_for_task(
              "extract invoice data", "extract_invoice").historical_failure_rate <= 1.0))
    check("get_best_repair_strategy() returns str or None",
          lambda: ok(retriever.get_best_repair_strategy(
              retriever.retrieve_for_task("extract invoice", "extract_invoice"))
              in (None,) or isinstance(retriever.get_best_repair_strategy(
              retriever.retrieve_for_task("extract invoice", "extract_invoice")), str)))
    check("get_recommended_prompt_additions() returns list[str]",
          lambda: ok(all(isinstance(p, str) for p in
              retriever.get_recommended_prompt_additions(
              retriever.retrieve_for_task("extract invoice", "extract_invoice")))))
    check("get_recommended_prompt_additions() no duplicates",
          lambda: ok(len(set(retriever.get_recommended_prompt_additions(
              retriever.retrieve_for_task("extract invoice", "extract_invoice")))) ==
              len(retriever.get_recommended_prompt_additions(
              retriever.retrieve_for_task("extract invoice", "extract_invoice")))))

    # 6. MemoryAdapter
    section("6. MemoryAdapter")
    adapter = MA(retriever)
    check("get_adapted_config() returns AdaptedExecutionConfig",
          lambda: ok(isinstance(
              adapter.get_adapted_config("extract invoice", "extract_invoice"), AEC)))
    check("no-memory case: all overrides None/empty/False/0",
          lambda: ok(
              adapter.get_adapted_config("quantum xyz", "unseen_node").n_drafts_override is None and
              adapter.get_adapted_config("quantum xyz", "unseen_node").memories_used == 0 and
              adapter.get_adapted_config("quantum xyz", "unseen_node").confidence == 0.0))
    check("adaptation_reason is non-empty string",
          lambda: ok(len(adapter.get_adapted_config(
              "extract invoice", "extract_invoice").adaptation_reason) > 0))
    check("confidence is in [0.0, 1.0]",
          lambda: ok(0.0 <= adapter.get_adapted_config(
              "extract invoice", "extract_invoice").confidence <= 1.0))
    check("memories_used is non-negative int",
          lambda: ok(adapter.get_adapted_config(
              "extract invoice", "extract_invoice").memories_used >= 0))
    check("schema violation history yields prompt additions",
          lambda: h_schema_adapt(adapter))
    check("record_execution_outcome() persists outcome",
          lambda: h_outcome(store, adapter, CFR, FT))

    # 7. Disk Persistence
    section("7. MemoryStore -- Disk Persistence")
    check("save + reopen + retrieve survives across instances",
          lambda: h_persistence(MS, CFR, FT))

    # 8. Full End-to-End Loop
    section("8. Full Proactive Feedback Loop")
    check("seed -> adapt -> record -> re-adapt full cycle",
          lambda: h_full_loop(MS, MR, MA, CFR, FT))

    store.close()

    # Summary
    total = _passed + _failed
    print(f"\n{'='*65}")
    print(f"{BOLD}  Smoke Test Summary{RESET}")
    print(f"  {'-'*60}")
    print(f"  Total  : {total}")
    print(f"  {GREEN}Passed : {_passed}{RESET}")
    if _failed:
        print(f"  {RED}Failed : {_failed}{RESET}")
        print(f"\n  {RED}FAILED CHECKS:{RESET}")
        for name, ok_, err in _log:
            if not ok_:
                print(f"    x {name}\n      {err}")
        print(f"{'='*65}\n")
        return False
    else:
        print(f"  {GREEN}Failed : 0{RESET}")
        print(f"\n  {GREEN}{BOLD}All smoke checks passed. FMB is healthy.{RESET}")
        print(f"{'='*65}\n")
        return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
