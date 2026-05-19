import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from specforge.cognition.reasoning.reasoning_config import (
    ReasoningPipelineConfig, BudgetForcerConfig, SocraticConfig
)


class TestBudgetForcerConfig:
    def test_defaults_populated(self):
        config = BudgetForcerConfig()
        assert config.min_reasoning_tokens == 200
        assert len(config.keep_going_phrases) > 0

    def test_custom_keep_going_phrases(self):
        config = BudgetForcerConfig()
        assert "Wait" in config.keep_going_phrases[0]
        assert "reconsider" in config.keep_going_phrases[1].lower()

    def test_max_reasoning_tokens_enforced(self):
        config = BudgetForcerConfig(min_reasoning_tokens=100, max_reasoning_tokens=200)
        assert config.max_reasoning_tokens > config.min_reasoning_tokens


class TestSocraticConfig:
    def test_defaults_populated(self):
        config = SocraticConfig()
        assert config.num_questions == 3
        assert config.question_temperature == 0.7
        assert config.answer_temperature == 0.4
        assert config.synthesis_temperature == 0.3

    def test_custom_num_questions(self):
        config = SocraticConfig(num_questions=5)
        assert config.num_questions == 5


class TestReasoningPipelineConfig:
    def test_sub_configs_auto_created(self):
        config = ReasoningPipelineConfig()
        assert config.budget_config is not None
        assert config.socratic_config is not None

    def test_custom_values_preserved(self):
        config = ReasoningPipelineConfig(
            use_socratic=False,
            budget_config=BudgetForcerConfig(min_reasoning_tokens=50)
        )
        assert config.use_socratic is False
        assert config.budget_config.min_reasoning_tokens == 50

    def test_both_features_can_be_disabled(self):
        config = ReasoningPipelineConfig(
            use_budget_forcing=False,
            use_socratic=False
        )
        assert not config.use_budget_forcing
        assert not config.use_socratic

    def test_model_and_base_url_configured(self):
        config = ReasoningPipelineConfig(
            model="llama2:7b",
            ollama_base_url="http://localhost:11435"
        )
        assert config.model == "llama2:7b"
        assert config.ollama_base_url == "http://localhost:11435"
