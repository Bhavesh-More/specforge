"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Any

from pydantic import AnyHttpUrl, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class SpecForgeConfig(BaseSettings):
    """SpecForge application configuration.

    All values loaded from environment variables or .env file.
    Uses pydantic-settings for validation and environment binding.

    Attributes:
        database_url: PostgreSQL async connection string.
        redis_url: Redis connection string.
        ollama_base_url: Base URL for the Ollama API.
        ollama_model: Default model for standard node execution.
        ollama_teacher_model: Larger model used for teacher/healing paths.
        ollama_temperature: Temperature for Ollama generation calls.
        secret_key: Application secret key for signing and encryption.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        max_retry_attempts: Global default max retry attempts.
        context_token_budget: Per-node context window budget in tokens.
        debug: Enable debug mode (colored console logging vs JSON).
    """

    database_url: PostgresDsn
    redis_url: RedisDsn
    ollama_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:11434")
    ollama_model: str = "llama3.2"
    ollama_teacher_model: str = "llama3.1:8b"
    ollama_temperature: float = 0.3
    secret_key: str
    log_level: str = "INFO"
    max_retry_attempts: int = 3
    context_token_budget: int = 1500
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_config() -> SpecForgeConfig:
    """Return a cached singleton SpecForgeConfig instance.

    Reads from .env file and environment variables on first call.
    Subsequent calls return the cached instance.
    """
    return SpecForgeConfig()
