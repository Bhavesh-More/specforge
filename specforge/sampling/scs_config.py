from dataclasses import dataclass, field


@dataclass
class SCSConfig:
    """Master config for the full SCS pipeline."""

    n_drafts: int = 5
    draft_length: int = 40
    draft_temperature: float = 0.85
    embed_model: str = "nomic-embed-text"
    confidence_threshold: float = 0.72
    outlier_suppression_factor: float = 0.3
    ollama_base_url: str = "http://localhost:11434"
    NODE_TYPE_N_OVERRIDES: dict = field(
        default_factory=lambda: {
            "classify": 1,
            "tag": 1,
            "extract": 2,
            "summarise": 3,
            "generate": 5,
            "plan": 5,
            "reason": 7,
            "multi_step": 7,
        }
    )

    def n_for_node_type(self, node_type: str) -> int:
        """Return the SCS draft count for a node type prefix."""
        lowered = node_type.lower()
        for prefix, n in self.NODE_TYPE_N_OVERRIDES.items():
            if lowered.startswith(prefix):
                return n
        return self.n_drafts