"""
Reasoning Pipeline Demo — run with: python -m specforge.demos.reasoning_demo
"""
import asyncio
import time
from specforge.cognition import ReasoningPipeline, ReasoningPipelineConfig, BudgetForcerConfig, SocraticConfig

REASONING_TASK = """
A company's revenue grew 23% in Q1, then declined 15% in Q2, then grew 31% in Q3.
If their Q4 revenue is $2.4M, what was their revenue at the start of Q1?
Also explain which quarter showed the most volatile change and why that matters
for financial forecasting.
"""

async def run_deep_reason():
    config = ReasoningPipelineConfig(
        use_budget_forcing=True,
        use_socratic=True,
        budget_config=BudgetForcerConfig(min_reasoning_tokens=200, max_reasoning_tokens=500),
        socratic_config=SocraticConfig(num_questions=3),
        model="llama3:8b",
    )
    pipeline = ReasoningPipeline(config)
    result = await pipeline.execute(REASONING_TASK)
    await pipeline.close()
    return result

if __name__ == "__main__":
    asyncio.run(run_deep_reason())
