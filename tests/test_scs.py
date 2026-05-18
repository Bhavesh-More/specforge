import numpy as np

from specforge.sampling.centroid_selector import CentroidSelector
from specforge.sampling.draft_sampler import Draft
from specforge.sampling.scs_config import SCSConfig
from specforge.sampling.similarity_engine import SimilarityMatrix


class TestSCSConfig:
    def test_classify_node_returns_1(self):
        config = SCSConfig()
        assert config.n_for_node_type("classify_sentiment") == 1

    def test_tag_node_returns_1(self):
        config = SCSConfig()
        assert config.n_for_node_type("tag_category") == 1

    def test_reason_node_returns_7(self):
        config = SCSConfig()
        assert config.n_for_node_type("reason_causal") == 7

    def test_extract_returns_2(self):
        config = SCSConfig()
        assert config.n_for_node_type("extract_invoice") == 2

    def test_unknown_node_returns_default(self):
        config = SCSConfig(n_drafts=4)
        assert config.n_for_node_type("my_custom_node") == 4

    def test_case_insensitive_matching(self):
        config = SCSConfig()
        assert config.n_for_node_type("CLASSIFY_SENTIMENT") == 1


def _make_drafts(n: int) -> list[Draft]:
    return [Draft(index=i, text=f"draft text {i}", seed=i * 1337, token_count=40) for i in range(n)]


def _make_sim(matrix: np.ndarray) -> SimilarityMatrix:
    n = len(matrix)
    return SimilarityMatrix(
        matrix=matrix,
        embeddings=np.random.randn(n, 768).astype(np.float32),
        draft_indices=list(range(n)),
    )


class TestCentroidSelector:
    def test_selects_highest_centrality_draft(self):
        matrix = np.array(
            [
                [1.00, 0.90, 0.88, 0.85],
                [0.90, 1.00, 0.40, 0.38],
                [0.88, 0.40, 1.00, 0.42],
                [0.85, 0.38, 0.42, 1.00],
            ]
        )
        drafts = _make_drafts(4)
        selector = CentroidSelector(confidence_threshold=0.5)
        result = selector.select(drafts, _make_sim(matrix))
        assert result.best_index == 0

    def test_outlier_draft_identified(self):
        matrix = np.array(
            [
                [1.00, 0.88, 0.86, 0.09],
                [0.88, 1.00, 0.90, 0.11],
                [0.86, 0.90, 1.00, 0.08],
                [0.09, 0.11, 0.08, 1.00],
            ]
        )
        drafts = _make_drafts(4)
        selector = CentroidSelector(confidence_threshold=0.5)
        result = selector.select(drafts, _make_sim(matrix))
        assert 3 in result.outlier_indices

    def test_should_escalate_when_low_confidence(self):
        matrix = np.array(
            [
                [1.0, 0.28, 0.31, 0.27],
                [0.28, 1.0, 0.29, 0.33],
                [0.31, 0.29, 1.0, 0.26],
                [0.27, 0.33, 0.26, 1.0],
            ]
        )
        drafts = _make_drafts(4)
        selector = CentroidSelector(confidence_threshold=0.72)
        result = selector.select(drafts, _make_sim(matrix))
        assert result.should_escalate is True

    def test_should_not_escalate_when_high_confidence(self):
        matrix = np.array(
            [
                [1.0, 0.92, 0.91, 0.90],
                [0.92, 1.0, 0.93, 0.91],
                [0.91, 0.93, 1.0, 0.89],
                [0.90, 0.91, 0.89, 1.0],
            ]
        )
        drafts = _make_drafts(4)
        selector = CentroidSelector(confidence_threshold=0.72)
        result = selector.select(drafts, _make_sim(matrix))
        assert result.should_escalate is False

    def test_single_draft_handled_gracefully(self):
        matrix = np.array([[1.0]])
        drafts = _make_drafts(1)
        selector = CentroidSelector()
        result = selector.select(drafts, _make_sim(matrix))
        assert result.best_index == 0
        assert result.confidence == 1.0
        assert result.cluster_size == 1
        assert result.outlier_indices == []

    def test_cluster_size_excludes_outliers(self):
        matrix = np.array(
            [
                [1.00, 0.88, 0.86, 0.09],
                [0.88, 1.00, 0.90, 0.11],
                [0.86, 0.90, 1.00, 0.08],
                [0.09, 0.11, 0.08, 1.00],
            ]
        )
        drafts = _make_drafts(4)
        selector = CentroidSelector(confidence_threshold=0.5)
        result = selector.select(drafts, _make_sim(matrix))
        assert result.cluster_size == 3

    def test_all_centrality_scores_length_matches_drafts(self):
        matrix = np.eye(3)
        drafts = _make_drafts(3)
        selector = CentroidSelector()
        result = selector.select(drafts, _make_sim(matrix))
        assert len(result.all_centrality_scores) == 3

    def test_soft_suppression_not_hard_removal(self):
        matrix = np.array(
            [
                [1.0, 0.15, 0.12],
                [0.15, 1.0, 0.14],
                [0.12, 0.14, 1.0],
            ]
        )
        drafts = _make_drafts(3)
        selector = CentroidSelector(outlier_suppression_factor=0.3)
        result = selector.select(drafts, _make_sim(matrix))
        assert result.best_draft is not None
        assert 0 <= result.best_index < 3