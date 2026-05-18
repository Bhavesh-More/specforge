from __future__ import annotations

from dataclasses import dataclass

import httpx

from .centroid_selector import CentroidSelector, SCSResult
from .draft_sampler import DraftSampler
from .scs_config import SCSConfig
from .similarity_engine import SimilarityEngine


@dataclass
class SCSGenerationResult:
    """Complete result from one SCS-guided node generation."""

    text: str
    scs_result: SCSResult | None
    prefix_used: str
    bypassed: bool
    should_escalate: bool
    total_draft_tokens: int
    full_generation_tokens: int


class SCSExecutor:
    """Full Speculative Consistency Sampling pipeline."""

    def __init__(self, config: SCSConfig | None = None):
        self.config = config or SCSConfig()
        self._sampler = DraftSampler(self.config)
        self._embedder = SimilarityEngine(self.config)
        self._selector = CentroidSelector(
            confidence_threshold=self.config.confidence_threshold,
            outlier_suppression_factor=self.config.outlier_suppression_factor,
        )
        self._client = httpx.AsyncClient(timeout=120.0)

    async def generate(
        self,
        model: str,
        prompt: str,
        node_type: str = "standard",
        max_tokens: int = 400,
        temperature: float = 0.7,
    ) -> SCSGenerationResult:
        n = self.config.n_for_node_type(node_type)
        if n <= 1:
            raw_text = await self._plain_generate(model, prompt, max_tokens, temperature)
            return SCSGenerationResult(
                text=raw_text,
                scs_result=None,
                prefix_used="",
                bypassed=True,
                should_escalate=False,
                total_draft_tokens=0,
                full_generation_tokens=len(raw_text.split()),
            )

        drafts = await self._sampler.sample_drafts(prompt, model, n=n)
        sim_matrix = await self._embedder.compute_similarity_matrix(drafts)
        scs_result = self._selector.select(drafts, sim_matrix)

        if scs_result.should_escalate:
            return SCSGenerationResult(
                text="",
                scs_result=scs_result,
                prefix_used="",
                bypassed=False,
                should_escalate=True,
                total_draft_tokens=sum(draft.token_count for draft in drafts),
                full_generation_tokens=0,
            )

        prefix = scs_result.best_draft.text
        prefixed_prompt = prompt + "\n\n" + prefix
        remaining_tokens = max(50, max_tokens - scs_result.best_draft.token_count)
        continuation = await self._plain_generate(
            model,
            prefixed_prompt,
            remaining_tokens,
            temperature,
        )
        full_text = prefix + continuation

        return SCSGenerationResult(
            text=full_text,
            scs_result=scs_result,
            prefix_used=prefix,
            bypassed=False,
            should_escalate=False,
            total_draft_tokens=sum(draft.token_count for draft in drafts),
            full_generation_tokens=len(full_text.split()),
        )

    async def _plain_generate(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        try:
            response = await self._client.post(
                f"{self.config.ollama_base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Generation request timed out after 120s at {self.config.ollama_base_url}"
            ) from exc
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.config.ollama_base_url}. Is Ollama running? Run: ollama serve"
            ) from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama returned {response.status_code} for generation: {response.text[:200]}"
            )

        return response.json()["response"].strip()

    async def close(self):
        await self._sampler.close()
        await self._embedder.close()
        await self._client.aclose()