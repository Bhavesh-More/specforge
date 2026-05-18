from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .draft_sampler import Draft
from .similarity_engine import SimilarityMatrix


@dataclass
class SCSResult:
    """Complete result from one round of Speculative Consistency Sampling."""

    best_draft: Draft
    best_index: int
    confidence: float
    cluster_size: int
    outlier_indices: list[int]
    all_centrality_scores: list[float]
    similarity_matrix: np.ndarray
    should_escalate: bool


class CentroidSelector:
    """Select the most consensual draft from a similarity matrix."""

    def __init__(
        self,
        confidence_threshold: float = 0.72,
        outlier_suppression_factor: float = 0.3,
    ):
        self.confidence_threshold = confidence_threshold
        self.outlier_suppression_factor = outlier_suppression_factor

    def select(self, drafts: list[Draft], sim: SimilarityMatrix) -> SCSResult:
        if len(drafts) == 1:
            return SCSResult(
                best_draft=drafts[0],
                best_index=0,
                confidence=1.0,
                cluster_size=1,
                outlier_indices=[],
                all_centrality_scores=[1.0],
                similarity_matrix=sim.matrix,
                should_escalate=False,
            )

        N = len(drafts)
        matrix = sim.matrix
        row_sums = matrix.sum(axis=1)
        centrality = (row_sums - 1.0) / (N - 1)

        if N >= 3:
            mean_c = centrality.mean()
            std_c = centrality.std()
            outlier_mask = centrality < (mean_c - std_c)
            outlier_indices = list(np.where(outlier_mask)[0].astype(int))
        else:
            outlier_mask = np.zeros(N, dtype=bool)
            outlier_indices = []

        adjusted = centrality.copy()
        adjusted[outlier_mask] *= self.outlier_suppression_factor

        best_index = int(np.argmax(adjusted))
        confidence = float(adjusted[best_index])
        cluster_size = int((~outlier_mask).sum())

        return SCSResult(
            best_draft=drafts[best_index],
            best_index=best_index,
            confidence=confidence,
            cluster_size=cluster_size,
            outlier_indices=outlier_indices,
            all_centrality_scores=centrality.tolist(),
            similarity_matrix=sim.matrix,
            should_escalate=confidence < self.confidence_threshold,
        )