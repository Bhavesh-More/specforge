from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from .scs_config import SCSConfig


@dataclass
class Draft:
    """One generated draft prefix."""

    index: int
    text: str
    seed: int
    token_count: int


class DraftSampler:
    """Generate N short draft prefixes from Ollama in parallel."""

    def __init__(self, config: SCSConfig):
        self.config = config
        self._client = httpx.AsyncClient(
            timeout=60.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def sample_drafts(
        self,
        prompt: str,
        model: str,
        n: int | None = None,
    ) -> list[Draft]:
        n_to_use = n if n is not None else self.config.n_drafts
        tasks = [
            self._generate_one_draft(prompt, model, index=i, seed=i * 1337)
            for i in range(n_to_use)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful: list[Draft] = []
        for i, result in enumerate(results):
            if isinstance(result, Draft):
                successful.append(result)
            else:
                print(f"Draft {i} failed: {result}")

        if len(successful) < 2:
            raise RuntimeError(
                f"SCS requires at least 2 successful drafts, got {len(successful)}. "
                f"Check Ollama is running at {self.config.ollama_base_url}"
            )

        return sorted(successful, key=lambda draft: draft.index)

    async def _generate_one_draft(
        self,
        prompt: str,
        model: str,
        index: int,
        seed: int,
    ) -> Draft:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": self.config.draft_length,
                "temperature": self.config.draft_temperature,
                "seed": seed,
            },
        }

        try:
            response = await self._client.post(
                f"{self.config.ollama_base_url}/api/generate",
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Draft {index} timed out after 60s") from exc
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.config.ollama_base_url}. Is Ollama running? Run: ollama serve"
            ) from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama returned {response.status_code} for draft {index}: {response.text[:200]}"
            )

        response_json = response.json()
        text = response_json["response"].strip()
        return Draft(
            index=index,
            text=text,
            seed=seed,
            token_count=len(response_json["response"].split()),
        )

    async def close(self):
        await self._client.aclose()