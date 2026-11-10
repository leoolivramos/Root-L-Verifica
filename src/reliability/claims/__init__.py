"""LLM integration (instructor + OpenAI-compatible endpoint)."""

from reliability.claims.models import (
    DEFAULT_OLLAMA_MODELS,
    VALID_OPENAI_MODELS,
    check_ollama_status,
    fetch_ollama_models,
    is_openai_model,
    is_reasoning_model,
)

__all__ = [
    "DEFAULT_OLLAMA_MODELS",
    "VALID_OPENAI_MODELS",
    "check_ollama_status",
    "fetch_ollama_models",
    "is_openai_model",
    "is_reasoning_model",
]
