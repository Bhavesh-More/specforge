"""Quick usage example for Speculative Consistency Sampling.

Run this after installing dependencies and starting Ollama locally.
It shows the minimum interface needed to call the new feature.
"""

from __future__ import annotations

import asyncio

from specforge.sampling import SCSConfig, SCSExecutor


async def main() -> None:
    config = SCSConfig()
    executor = SCSExecutor(config)

    try:
        result = await executor.generate(
            model="llama3.1:8b",
            prompt="Explain the main trade-offs of using caching in an API service.",
            node_type="reason_analysis",
            max_tokens=300,
            temperature=0.7,
        )

        if result.bypassed:
            print("SCS was bypassed for this node type.")
            print(result.text)
            return

        if result.should_escalate:
            print("SCS confidence was too low, so you should fall back to your escalation path.")
            print(f"Confidence: {result.scs_result.confidence:.3f}")
            return

        print("SCS-guided output:")
        print(result.text)
        print()
        print(f"Confidence: {result.scs_result.confidence:.3f}")
        print(f"Prefix used: {result.prefix_used}")
        print(f"Draft tokens spent: {result.total_draft_tokens}")

    finally:
        await executor.close()


if __name__ == "__main__":
    asyncio.run(main())