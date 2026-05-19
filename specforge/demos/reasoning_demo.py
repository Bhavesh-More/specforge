"""
Reasoning Pipeline Demo — run with: python -m specforge.demos.reasoning_demo

Shows:
1. Vanilla generation on a hard reasoning task
2. Budget Forcing only
3. Socratic + Budget Forcing (full deep_reason pipeline)
"""
import asyncio
import time
import httpx
from specforge.cognition import (
    ReasoningPipeline, ReasoningPipelineConfig, 
    BudgetForcerConfig, SocraticConfig
)

REASONING_TASK = """
A company's revenue grew 23% in Q1, then declined 15% in Q2, then grew 31% in Q3.
If their Q4 revenue is $2.4M, what was their revenue at the start of Q1?
Also explain which quarter showed the most volatile change and why that matters
for financial forecasting.
"""

async def run_vanilla():
    """Plain Ollama call without any reasoning enhancement."""
    client = httpx.AsyncClient(timeout=120.0)
    try:
        resp = await client.post("http://localhost:11434/api/generate", json={
            "model": "llama3.1:8b", 
            "prompt": REASONING_TASK, 
            "stream": False,
            "options": {"num_predict": 300, "temperature": 0.7}
        })
        data = resp.json()
        return data.get("response", "")
    finally:
        await client.aclose()

async def run_budget_forcing_only():
    """Budget Forcing alone — forces minimum reasoning depth."""
    config = ReasoningPipelineConfig(
        use_budget_forcing=True,
        use_socratic=False,
        budget_config=BudgetForcerConfig(min_reasoning_tokens=200, max_reasoning_tokens=500),
        model="llama3.1:8b",
    )
    pipeline = ReasoningPipeline(config)
    result = await pipeline.execute(REASONING_TASK)
    await pipeline.close()
    return result

async def run_deep_reason():
    """Full deep_reason pipeline: Socratic + Budget Forcing."""
    config = ReasoningPipelineConfig(
        use_budget_forcing=True,
        use_socratic=True,
        budget_config=BudgetForcerConfig(min_reasoning_tokens=200, max_reasoning_tokens=500),
        socratic_config=SocraticConfig(num_questions=3),
        model="llama3.1:8b",
    )
    pipeline = ReasoningPipeline(config)
    result = await pipeline.execute(REASONING_TASK)
    await pipeline.close()
    return result

async def main():
    print("=" * 70)
    print("SpecForge — Deep Reasoning Pipeline Demo")
    print("=" * 70)
    print("\nTask: Multi-quarter revenue calculation + forecasting analysis")
    print("=" * 70)

    # ── Run 1: Vanilla ────────────────────────────────────────────────────
    print("\n[1/3] Vanilla generation (no reasoning enhancement)...")
    t0 = time.time()
    vanilla_output = await run_vanilla()
    vanilla_time = time.time() - t0
    
    print(f"✓ Completed in {vanilla_time:.2f}s")
    print("\n  Output:")
    print("  " + "-" * 66)
    for line in vanilla_output[:250].split("\n"):
        print(f"  {line}")
    if len(vanilla_output) > 250:
        print("  [... truncated ...]")
    print("  " + "-" * 66)

    # ── Run 2: Budget Forcing only ────────────────────────────────────────
    print("\n[2/3] Budget Forcing only (enforced thinking depth)...")
    t0 = time.time()
    budget_result = await run_budget_forcing_only()
    budget_time = time.time() - t0
    
    print(f"✓ Completed in {budget_time:.2f}s")
    print(f"  Pipeline: {budget_result.pipeline_used}")
    
    if budget_result.budget_result:
        print(f"\n  Reasoning trace ({budget_result.budget_result.reasoning_token_count} tokens):")
        print("  " + "-" * 66)
        reasoning_preview = budget_result.budget_result.reasoning_trace[:300]
        for line in reasoning_preview.split("\n"):
            if line.strip():
                print(f"  {line}")
        print("  " + "-" * 66)
        print(f"  Early exit attempts suppressed: {budget_result.budget_result.early_exit_attempts}")

    # ── Run 3: Full Deep Reason ───────────────────────────────────────────
    print("\n[3/3] Deep Reason pipeline (Socratic + Budget Forcing)...")
    t0 = time.time()
    result = await run_deep_reason()
    deep_reason_time = time.time() - t0
    
    print(f"✓ Completed in {deep_reason_time:.2f}s")
    print(f"  Pipeline used: {result.pipeline_used}")

    if result.socratic_result:
        print(f"\n  Socratic decomposition ({len(result.socratic_result.sub_questions)} sub-questions):")
        for sq in result.socratic_result.sub_questions:
            print(f"\n    Q{sq.index}: {sq.question}")
            print(f"    A{sq.index}: {sq.answer[:100].strip()}...")

    if result.budget_result:
        print(f"\n  Reasoning trace ({result.budget_result.reasoning_token_count} tokens):")
        print("  " + "-" * 66)
        reasoning_preview = result.budget_result.reasoning_trace[:300]
        for line in reasoning_preview.split("\n"):
            if line.strip():
                print(f"  {line}")
        print("  " + "-" * 66)
        print(f"  Early exit attempts suppressed: {result.budget_result.early_exit_attempts}")

    # ── Comparison ────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("Performance Comparison")
    print("=" * 70)
    print(f"  Vanilla:              {vanilla_time:.2f}s")
    print(f"  Budget Forcing only:  {budget_time:.2f}s")
    print(f"  Full Deep Reason:     {deep_reason_time:.2f}s")

    print("\n" + "=" * 70)
    print("Final Answer (Deep Reason)")
    print("=" * 70)
    print(result.final_answer[:600])
    if len(result.final_answer) > 600:
        print("\n[... truncated ...]")

    print("\n" + "=" * 70)
    print("Demo complete.")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
