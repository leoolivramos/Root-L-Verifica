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

    llm_provider: str = "auto"  # auto | ollama | openai
    llm_base_url: str = "https://api.openai.com/v1"
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_context_tokens: int = 128_000
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 3
    llm_mode: str = "auto"  # auto | tools | json

    @property
    def effective_api_key(self) -> str:
        """Returns the configured API key based on the target endpoint."""
        if "localhost" in self.llm_base_url or "127.0.0.1" in self.llm_base_url:
            if self.llm_api_key and self.llm_api_key.strip():
                return self.llm_api_key.strip()
            return "ollama"
        if self.openai_api_key and self.openai_api_key.strip():
            return self.openai_api_key.strip()
        if self.llm_api_key and self.llm_api_key.strip():
            return self.llm_api_key.strip()
        return ""

    def for_provider(
        self,
        provider: str,
        model: str | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> Settings:
        """Return a new Settings copy tuned for the requested provider and model."""
        prov = provider.lower().strip()
        if "openai" in prov or "nuvem" in prov:
            chosen_model = model or "gpt-4o-mini"
            chosen_url = base_url or self.openai_base_url or "https://api.openai.com/v1"
            chosen_key = (
                api_key.strip()
                if api_key and api_key.strip()
                else (self.openai_api_key.strip() if self.openai_api_key else self.llm_api_key.strip())
            )
            from reliability.claims.models import is_reasoning_model

            chosen_mode = "json" if is_reasoning_model(chosen_model) else "tools"
            return self.model_copy(
                update={
                    "llm_provider": "openai",
                    "llm_model": chosen_model,
                    "llm_base_url": chosen_url,
                    "openai_api_key": chosen_key,
                    "llm_api_key": chosen_key,
                    "llm_context_tokens": 128_000,
                    "llm_timeout_s": 60.0,
                    "llm_mode": chosen_mode,
                }
            )
        if "ollama" in prov or "local" in prov:
            chosen_model = model or "llama3.2"
            chosen_url = base_url or self.ollama_base_url or "http://localhost:11434/v1"
            chosen_key = api_key.strip() if (api_key and api_key.strip()) else "ollama"
            return self.model_copy(
                update={
                    "llm_provider": "ollama",
                    "llm_model": chosen_model,
                    "llm_base_url": chosen_url,
                    "llm_api_key": chosen_key,
                    "llm_context_tokens": 8192,
                    "llm_timeout_s": 120.0,
                    "llm_mode": "json",
                }
            )
        return self.model_copy(
            update={
                "llm_model": model or self.llm_model,
                "llm_base_url": base_url or self.llm_base_url,
                "llm_api_key": api_key or self.llm_api_key,
            }
        )

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
