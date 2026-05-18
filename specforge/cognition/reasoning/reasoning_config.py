from dataclasses import dataclass
from typing import Optional

@dataclass
class BudgetForcerConfig:
    min_reasoning_tokens: int = 200
    max_reasoning_tokens: int = 600
    keep_going_phrases: list[str] = None

    def __post_init__(self):
        if self.keep_going_phrases is None:
            self.keep_going_phrases = [
                "\n\nWait, I should think about this more carefully.",
                "\n\nLet me reconsider — I haven't examined all angles.",
                "\n\nActually, let me question that assumption.",
                "\n\nI need to think through potential edge cases here.",
            ]


@dataclass
class SocraticConfig:
    num_questions: int = 3
    question_max_tokens: int = 150
    answer_max_tokens: int = 120
    synthesis_max_tokens: int = 400
    question_temperature: float = 0.7
    answer_temperature: float = 0.4
    synthesis_temperature: float = 0.3


@dataclass
class ReasoningPipelineConfig:
    use_budget_forcing: bool = True
    use_socratic: bool = True
    budget_config: BudgetForcerConfig = None
    socratic_config: SocraticConfig = None
    ollama_base_url: str = "http://localhost:11434"
    model: str = "llama3:8b"

    def __post_init__(self):
        if self.budget_config is None:
            self.budget_config = BudgetForcerConfig()
        if self.socratic_config is None:
            self.socratic_config = SocraticConfig()
