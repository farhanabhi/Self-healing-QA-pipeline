"""
Centralised, strictly-typed configuration for the whole platform.

Every module (mock server, page objects, healer, tests) imports a single
`settings` instance from here instead of reading `os.environ` directly.
This keeps configuration validated in one place and makes the framework
trivially testable (override via environment variables or a `.env` file).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings, loaded from env vars / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Target under test ---
    mock_server_url: str = Field(
        default="http://localhost:8000",
        description="Base URL of the mock service virtualization layer.",
    )

    # --- Playwright / browser behaviour ---
    headless: bool = Field(default=True)
    default_action_timeout_ms: int = Field(
        default=3000,
        description="Timeout used for a locator action before the self-healer engages.",
    )
    slow_mo_ms: int = Field(default=0, description="Artificial delay for local debugging.")

    # --- AI self-healing ---
    self_healing_enabled: bool = Field(default=True)
    groq_api_key: str | None = Field(default=None)
    groq_model: str = Field(default="llama-3.1-8b-instant")
    max_heal_retries: int = Field(default=2, ge=0, le=5)
    heal_llm_timeout_seconds: float = Field(default=15.0)

    # --- Reporting ---
    allure_results_dir: str = Field(default="allure-results")
    environment: Literal["local", "docker", "ci"] = Field(default="local")

    @property
    def self_healing_available(self) -> bool:
        """Self-healing needs both the feature flag AND a live API key."""
        return self.self_healing_enabled and bool(self.groq_api_key)


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor so we parse the environment exactly once."""
    return Settings()


settings = get_settings()
