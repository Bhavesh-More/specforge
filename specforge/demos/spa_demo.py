"""
SPA Demo — run with: python -m specforge.demos.spa_demo

Shows:
1. Vanilla generation (no SPA) with entropy printed per token
2. SPA-enabled generation with injection events highlighted
3. Side-by-side comparison of entropy curves printed to terminal
"""
import asyncio
import sys
import time
from specforge.cognition import SPAExecutor, SPAConfig

DEMO_PROMPT = """
Explain in detail the technical differences between transformer-based language models
and recurrent neural networks, covering attention mechanisms, parallelisation,
memory requirements, and practical deployment considerations.
"""

async def run_vanilla(prompt: str):
    """Run without SPA — collect entropy readings."""
    executor = SPAExecutor()
    # Pass a permissive config so injections never fire
    config = SPAConfig(warn_threshold=0.99, inject_threshold=0.99)
    result = await executor.generate(
        model="llama3.1:8b",
        prompt=prompt,
        spa_config=config,
        max_tokens=400,
    )
    await executor.close()
    return result

async def run_with_spa(prompt: str):
    """Run with SPA active."""
    executor = SPAExecutor()
    config = SPAConfig(warn_threshold=0.28, inject_threshold=0.48)
    result = await executor.generate(
        model="llama3.1:8b",
        prompt=prompt,
        spa_config=config,
        max_tokens=400,
    )
    await executor.close()
    return result

def print_entropy_bar(entropy: float, width: int = 40) -> str:
    """ASCII entropy bar chart."""
    filled = int(entropy * width)
    bar = "█" * filled + "░" * (width - filled)
    zone = "🔴" if entropy > 0.48 else "🟡" if entropy > 0.28 else "🟢"
    return f"{zone} [{bar}] {entropy:.3f}"

async def main():
    print("=" * 70)
    print("SpecForge — Semantic Pressure Annealing (SPA) Demo")
    print("=" * 70)
    print("\nTask: LLM technical comparison")
    print("=" * 70)

    print("\n[1/2] Running WITHOUT SPA (baseline)...")
    t0 = time.time()
    vanilla = await run_vanilla(DEMO_PROMPT)
    vanilla_time = time.time() - t0
    print(f"✓ Generated {vanilla.total_tokens} tokens in {vanilla_time:.2f}s")
    print(f"  Final entropy: {vanilla.final_smoothed_entropy:.3f}")
    print(f"  No injections (SPA disabled)")

    print("\n[2/2] Running WITH SPA (active monitoring)...")
    t0 = time.time()
    with_spa = await run_with_spa(DEMO_PROMPT)
    spa_time = time.time() - t0
    print(f"✓ Generated {with_spa.total_tokens} tokens in {spa_time:.2f}s")
    print(f"  Final entropy: {with_spa.final_smoothed_entropy:.3f}")
    print(f"  Pressure injections: {with_spa.injection_count}")

    if with_spa.pressure_events:
        print("\n--- Injection Events (mid-generation course corrections) ---")
        for i, event in enumerate(with_spa.pressure_events, 1):
            print(f"  [{i}] Token {event.token_index:4d} | "
                  f"entropy={event.entropy_at_trigger:.3f} | "
                  f"zone={event.zone.value}")
            print(f"       → {repr(event.suffix_injected[:60])}")

    print("\n--- Entropy Timeline Comparison (every 20 tokens) ---")
    print("  (Baseline vs SPA)")
    print("  Token    Baseline              SPA")
    print("  " + "-" * 60)
    
    max_tokens = max(len(vanilla.entropy_readings), len(with_spa.entropy_readings))
    for i in range(0, max_tokens, 20):
        vanilla_entropy = vanilla.entropy_readings[i].smoothed_entropy if i < len(vanilla.entropy_readings) else 0.0
        spa_entropy = with_spa.entropy_readings[i].smoothed_entropy if i < len(with_spa.entropy_readings) else 0.0
        
        vanilla_bar = print_entropy_bar(vanilla_entropy, 18)
        spa_bar = print_entropy_bar(spa_entropy, 18)
        print(f"  {i:5d}    {vanilla_bar}   {spa_bar}")

    print("\n--- Performance Impact ---")
    print(f"  Vanilla generation:    {vanilla_time:.2f}s, {vanilla.total_tokens} tokens")
    print(f"  SPA generation:        {spa_time:.2f}s, {with_spa.total_tokens} tokens")
    if vanilla_time > 0:
        speedup = vanilla_time / spa_time if spa_time > 0 else 1.0
        print(f"  Speedup:               {speedup:.2f}x faster with SPA")

    print("\n--- Final Output (with SPA) ---")
    print("-" * 70)
    output_preview = with_spa.text[:600]
    if len(with_spa.text) > 600:
        output_preview += "\n... [truncated] ..."
    print(output_preview)
    print("-" * 70)

    print("\n" + "=" * 70)
    print("Demo complete.")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())

