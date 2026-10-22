"""Application settings and version constants (RNF-07)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PIPELINE_VERSION = "0.1.0"
PROMPT_VERSION = "2026-10-b"

# Approximate chars per token used for context budgeting (no dedicated tokenizer).
CHARS_PER_TOKEN = 3.5


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_context_tokens: int = 128_000
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 3
    llm_mode: str = "auto"  # auto | tools | json

    @property
    def effective_api_key(self) -> str:
        """Returns the configured API key, preferring OPENAI_API_KEY if defined."""
        if self.openai_api_key and self.openai_api_key.strip():
            return self.openai_api_key.strip()
        return self.llm_api_key.strip()

    search_provider: str = "auto"  # auto | duckduckgo | tavily
    tavily_api_key: str = ""

    db_path: str = "data/reliability.db"
    outdated_after_days: int = 365

    reliability_demo: bool = False

    # Fetching limits (supports HTML, images and short video clips)
    fetch_max_bytes: int = 15_000_000
    fetch_timeout_s: float = 15.0
    fetch_max_redirects: int = 5
    allowed_ports: tuple[int, ...] = (80, 443, 8080, 8443)

    # Input limits
    max_input_chars: int = 200_000

    @property
    def db_file(self) -> Path:
        return Path(self.db_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
