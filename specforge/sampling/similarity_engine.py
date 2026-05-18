from __future__ import annotations

from dataclasses import dataclass

import httpx
import numpy as np

from .draft_sampler import Draft
from .scs_config import SCSConfig


@dataclass
class SimilarityMatrix:
    """Result of embedding and cosine similarity computation."""

    matrix: np.ndarray
    embeddings: np.ndarray
    draft_indices: list[int]


class SimilarityEngine:
    """Compute pairwise cosine similarity between draft embeddings."""

    def __init__(self, config: SCSConfig):
        self.config = config
        self._client = httpx.AsyncClient(timeout=30.0)

    async def compute_similarity_matrix(self, drafts: list[Draft]) -> SimilarityMatrix:
        texts = [draft.text for draft in drafts]
        embeddings = await self._embed_texts(texts)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normed = embeddings / (norms + 1e-9)
        matrix = normed @ normed.T
        matrix = np.clip(matrix, 0.0, 1.0)
        return SimilarityMatrix(
            matrix=matrix,
            embeddings=embeddings,
            draft_indices=[draft.index for draft in drafts],
        )

    async def _embed_texts(self, texts: list[str]) -> np.ndarray:
        try:
            response = await self._client.post(
                f"{self.config.ollama_base_url}/api/embed",
                json={"model": self.config.embed_model, "input": texts},
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError("Embedding request timed out after 30s") from exc
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.config.ollama_base_url}. Is Ollama running? Run: ollama serve"
            ) from exc

        if response.status_code == 404:
            raise RuntimeError(
                f"Embedding model '{self.config.embed_model}' not found in Ollama. Run: ollama pull {self.config.embed_model}"
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama returned {response.status_code} for embeddings: {response.text[:200]}"
            )

        data = response.json()
        embeddings = data.get("embeddings")
        if embeddings is not None:
            return np.array(embeddings, dtype=np.float32)

        legacy_vectors: list[np.ndarray] = []
        for text in texts:
            legacy_response = await self._client.post(
                f"{self.config.ollama_base_url}/api/embeddings",
                json={"model": self.config.embed_model, "prompt": text},
            )
            if legacy_response.status_code == 404:
                raise RuntimeError(
                    f"Embedding model '{self.config.embed_model}' not found in Ollama. Run: ollama pull {self.config.embed_model}"
                )
            if legacy_response.status_code != 200:
                raise RuntimeError(
                    f"Ollama returned {legacy_response.status_code} for embeddings: {legacy_response.text[:200]}"
                )
            legacy_data = legacy_response.json()
            legacy_vectors.append(np.array(legacy_data["embedding"], dtype=np.float32))

        return np.stack(legacy_vectors, axis=0)

    async def close(self):
        await self._client.aclose()