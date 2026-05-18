"""
SPA Demo — run with: python -m specforge.demos.spa_demo
"""
import asyncio
import sys
from specforge.cognition import SPAExecutor, SPAConfig

DEMO_PROMPT = """
Explain in detail the technical differences between transformer-based language models
and recurrent neural networks, covering attention mechanisms, parallelisation,
memory requirements, and practical deployment considerations.
"""

async def run_vanilla(prompt: str):
    executor = SPAExecutor()
    config = SPAConfig(warn_threshold=0.99, inject_threshold=0.99)
    result = await executor.generate(
        model="llama3:8b",
        prompt=prompt,
        spa_config=config,
        max_tokens=400,
    )
    await executor.close()
    return result

async def run_with_spa(prompt: str):
    executor = SPAExecutor()
    config = SPAConfig(warn_threshold=0.28, inject_threshold=0.48)
    result = await executor.generate(
        model="llama3:8b",
        prompt=prompt,
        spa_config=config,
        max_tokens=400,
    )
    await executor.close()
    return result

if __name__ == "__main__":
    asyncio.run(run_with_spa(DEMO_PROMPT))
