"""Catalog of valid LLM models and discovery helpers for Ollama and OpenAI."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Final

logger = logging.getLogger(__name__)

# Valid curated models for OpenAI
VALID_OPENAI_MODELS: Final[list[str]] = [
    "gpt-6-astra",
    "gpt-6.1-sol",
    "gpt-6.1-terra",
    "gpt-6-luna",
    "gpt-4o-mini",
    "gpt-4o",
    "o3-mini",
    "o1-mini",
    "gpt-4-turbo",
    "gpt-3.5-turbo",
]

# Fallback models for Ollama when local daemon is unreachable
DEFAULT_OLLAMA_MODELS: Final[list[str]] = [
    "llama3.2",
    "llama3.3",
    "deepseek-r1:7b",
    "qwen2.5:7b-instruct",
    "mistral",
    "gemma2",
]


def is_openai_model(model_name: str) -> bool:
    """Return True if model name corresponds to OpenAI family."""
    name = model_name.lower().strip()
    return name.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))


def is_reasoning_model(model_name: str) -> bool:
    """Return True if model is a reasoning/thinking model with strict parameter constraints."""
    name = model_name.lower().strip()
    return any(
        k in name
        for k in (
            "o1",
            "o3",
            "o4",
            "luna",
            "astra",
            "sol",
            "terra",
            "gpt-5",
            "gpt-6",
            "deepseek-r1",
            "r1",
            "thinking",
            "reasoning",
        )
    )


def fetch_ollama_models(
    host: str = "http://localhost:11434",
    timeout_s: float = 2.0,
) -> list[str]:
    """Query local Ollama daemon for installed models.

    Returns installed model names if daemon is reachable, otherwise DEFAULT_OLLAMA_MODELS.
    """
    clean_host = host.rstrip("/")
    if clean_host.endswith("/v1"):
        clean_host = clean_host[:-3]

    url = f"{clean_host}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ReliabilityLab/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
            models = [m.get("name") for m in payload.get("models", []) if m.get("name")]
            if models:
                return models
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("Ollama not reachable at %s: %s", url, exc)

    return list(DEFAULT_OLLAMA_MODELS)


def check_ollama_status(
    host: str = "http://localhost:11434",
    timeout_s: float = 1.5,
) -> tuple[bool, str]:
    """Check whether local Ollama daemon is active and return status details."""
    clean_host = host.rstrip("/")
    if clean_host.endswith("/v1"):
        clean_host = clean_host[:-3]

    url = f"{clean_host}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ReliabilityLab/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
            count = len(payload.get("models", []))
            return True, f"Ollama online ({count} modelo{'s' if count != 1 else ''} instalado{'s' if count != 1 else ''})"
    except Exception as exc:
        return False, f"Ollama indisponível ({exc.__class__.__name__})"
