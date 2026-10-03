"""Application configuration, read from the environment and validated once."""

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every value the service needs, validated at startup rather than at use."""

    model_config = SettingsConfigDict(frozen=True)

    database_url: PostgresDsn
    inference_backend: Literal["fake", "ollama"] = "fake"
    ollama_url: str = "http://127.0.0.1:11434"
    chat_model: str = "fake-chat"
    embedding_model: str = "fake-embed"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, parsed on first call."""
    # Values come from the environment, which Pyright cannot see.
    return Settings()  # pyright: ignore[reportCallIssue]
