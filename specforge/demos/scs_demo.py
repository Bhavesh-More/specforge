"""SCS Demo - Speculative Consistency Sampling."""

from __future__ import annotations

import asyncio
import os
import time

import httpx
import numpy as np

from specforge.sampling import CentroidSelector, DraftSampler, SCSConfig, SCSExecutor, SimilarityEngine


DEMO_TASK = """
Analyse the three most important technical challenges in deploying large language
models in production for an enterprise. For each challenge, provide a concrete
engineering solution and explain the trade-offs involved.
"""

DEFAULT_MODEL = os.getenv("SPECFORGE_SCS_MODEL", "llama3.1:8b")
GENERATION_MODEL_HINTS = (
    "embed",
    "embedding",
    "nomic-embed-text",
)


async def resolve_demo_model(base_url: str, preferred_model: str) -> str:
    """Return an installed Ollama model, preferring the configured model."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{base_url}/api/tags")
        response.raise_for_status()

        data = response.json()

    models = [item.get("name", "") for item in data.get("models", []) if item.get("name")]
    generation_models = [
        name for name in models
        if not any(hint in name.lower() for hint in GENERATION_MODEL_HINTS)
    ]

    if not generation_models:
        raise RuntimeError(
            "No generation-capable Ollama models were found. "
            f"Installed models: {', '.join(models) if models else 'none'}. "
            f"Pull one first, for example: ollama pull {preferred_model}"
        )

    if preferred_model in generation_models:
        return preferred_model

    fallback = generation_models[0]
    print(
        f"  ⚠ Preferred model '{preferred_model}' is not installed; using '{fallback}' instead."
    )
    return fallback


def print_similarity_heatmap(matrix: np.ndarray) -> None:
    n = len(matrix)
    print("\n  Similarity matrix (████ >0.85  ▓▓▓ >0.70  ▒▒ >0.50  ░ <=0.50)")
    header = "      " + "  ".join(f" D{i + 1} " for i in range(n))
    print(header)
    for i in range(n):
        row_str = f"  D{i + 1}  |"
        for j in range(n):
            if i == j:
                row_str += "  —  "
            else:
                value = matrix[i, j]
                if value > 0.85:
                    row_str += " ████"
                elif value > 0.70:
                    row_str += " ▓▓▓ "
                elif value > 0.50:
                    row_str += " ▒▒  "
                else:
                    row_str += " ░   "
        print(row_str)


def print_centrality_bar(score: float, width: int = 30) -> str:
    filled = int(score * width)
    return "█" * filled + "░" * (width - filled) + f"  {score:.4f}"


async def main() -> None:
    print("=" * 65)
    print("  SpecForge - Speculative Consistency Sampling Demo")
    print("=" * 65)

    config = SCSConfig(
        n_drafts=5,
        draft_length=40,
        draft_temperature=0.85,
        confidence_threshold=0.72,
    )

    model = await resolve_demo_model(config.ollama_base_url, DEFAULT_MODEL)
    print(f"  Using Ollama model: {model}")

    print(
        f"\n[1/4] Generating {config.n_drafts} parallel drafts "
        f"({config.draft_length} tokens each)..."
    )
    sampler = DraftSampler(config)
    t_start = time.perf_counter()
    drafts = await sampler.sample_drafts(DEMO_TASK, model)
    t_drafts = time.perf_counter() - t_start

    print(
        f"  ✓ All {len(drafts)} drafts completed in {t_drafts:.2f}s "
        f"(parallel - wall-clock ≈ 1 draft's time)"
    )
    print()
    for draft in drafts:
        print(f"  Draft {draft.index + 1} [seed={draft.seed}]:")
        print(f"    {draft.text[:90].strip()}...")

    print(
        f"\n[2/4] Computing semantic similarity matrix "
        f"(embedding model: {config.embed_model})..."
    )
    embedder = SimilarityEngine(config)
    t_start = time.perf_counter()
    sim = await embedder.compute_similarity_matrix(drafts)
    t_embed = time.perf_counter() - t_start

    print(f"  ✓ Embeddings computed in {t_embed:.2f}s (embedding dim: {sim.embeddings.shape[1]})")
    print_similarity_heatmap(sim.matrix)

    print("\n[3/4] Selecting centroid draft...")
    selector = CentroidSelector(
        confidence_threshold=config.confidence_threshold,
        outlier_suppression_factor=config.outlier_suppression_factor,
    )
    result = selector.select(drafts, sim)

    print("\n  Centrality scores (mean cosine sim to all other drafts):")
    for i, score in enumerate(result.all_centrality_scores):
        is_winner = i == result.best_index
        is_outlier = i in result.outlier_indices
        tag = "  ← WINNER" if is_winner else ("  [OUTLIER]" if is_outlier else "")
        print(f"  Draft {i + 1}:  {print_centrality_bar(score)}{tag}")

    print(f"\n  Confidence:       {result.confidence:.4f}  (threshold: {config.confidence_threshold})")
    print(f"  Cluster size:     {result.cluster_size} / {len(drafts)} non-outlier drafts")
    print(f"  Should escalate:  {result.should_escalate}")
    print("\n  Selected prefix:")
    print(f"    {result.best_draft.text.strip()}")

    if result.should_escalate:
        print("\n  ⚠ Confidence below threshold - would escalate to adversarial triad.")
        print("    (Skipping full generation in demo.)")
    else:
        print("\n[4/4] Running full generation with winning prefix...")
        executor = SCSExecutor(config)
        t_start = time.perf_counter()
        gen_result = await executor.generate(
            model=model,
            prompt=DEMO_TASK,
            node_type="reason_analysis",
            max_tokens=400,
        )
        t_full = time.perf_counter() - t_start

        print(f"  ✓ Full generation completed in {t_full:.2f}s")
        print(f"  Draft tokens spent:    {gen_result.total_draft_tokens}")
        print(f"  Full generation tokens: {gen_result.full_generation_tokens}")

        naive_cost = 7 * 400
        scs_cost = gen_result.total_draft_tokens + gen_result.full_generation_tokens
        saving = round((1 - scs_cost / naive_cost) * 100)
        print("\n  Token cost comparison:")
        print(f"    Naive self-consistency (N=7 full): ~{naive_cost} tokens")
        print(f"    SCS (N=5 drafts + 1 full):         ~{scs_cost} tokens")
        print(f"    Saving:                             ~{saving}%")

        print("\n  Final output:")
        print("  " + "-" * 60)
        for line in gen_result.text[:600].split("\n"):
            print(f"  {line}")
        if len(gen_result.text) > 600:
            print("  [... truncated ...]")

        await executor.close()

    await sampler.close()
    await embedder.close()

    print("\n" + "=" * 65)
    print("  Demo complete.")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())