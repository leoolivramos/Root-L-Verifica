"""Tests for model selection, provider switching, and Ollama/OpenAI discovery."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import instructor

from reliability.claims.llm import InstructorGateway
from reliability.claims.models import (
    DEFAULT_OLLAMA_MODELS,
    VALID_OPENAI_MODELS,
    check_ollama_status,
    fetch_ollama_models,
    is_openai_model,
    is_reasoning_model,
)
from reliability.config import Settings
from reliability.demo import FakeLLMGateway
from reliability.jobs import JobManager


def test_is_openai_model_identification():
    for m in VALID_OPENAI_MODELS:
        assert is_openai_model(m), f"Expected {m} to be recognized as OpenAI model"
    assert is_openai_model("chatgpt-4o-latest")
    assert is_openai_model("o1-preview")
    assert is_openai_model("o3-mini")

    for m in DEFAULT_OLLAMA_MODELS:
        assert not is_openai_model(m), f"Expected {m} not to be recognized as OpenAI model"


def test_is_reasoning_model_identification():
    reasoning_names = [
        "gpt-6-astra",
        "gpt-6.1-sol",
        "gpt-6.1-terra",
        "gpt-6-luna",
        "o1",
        "o1-mini",
        "o3-mini",
        "deepseek-r1:7b",
    ]
    for m in reasoning_names:
        assert is_reasoning_model(m), f"Expected {m} to be recognized as reasoning model"

    standard_names = ["gpt-4o", "gpt-4o-mini", "llama3.2", "qwen2.5:7b-instruct"]
    for m in standard_names:
        assert not is_reasoning_model(m), f"Expected {m} not to be marked as reasoning model"


def test_instructor_gateway_mode_for_reasoning_models():
    # Reasoning models should use Mode.JSON instead of Mode.TOOLS to avoid function tools with reasoning conflict
    gw_reasoning = InstructorGateway(model="gpt-6-astra", api_key="test-key")
    assert gw_reasoning._client.mode == instructor.Mode.JSON
    assert gw_reasoning._is_reasoning is True

    # Standard OpenAI models should default to Mode.TOOLS in auto mode
    gw_standard = InstructorGateway(model="gpt-4o-mini", api_key="test-key")
    assert gw_standard._client.mode == instructor.Mode.TOOLS
    assert gw_standard._is_reasoning is False


def test_fetch_ollama_models_fallback_on_error():
    # An invalid unreachable address should safely return the fallback list
    models = fetch_ollama_models(host="http://127.0.0.1:59999", timeout_s=0.2)
    assert models == list(DEFAULT_OLLAMA_MODELS)


def test_fetch_ollama_models_success():
    payload = json.dumps({"models": [{"name": "llama3.2:latest"}, {"name": "deepseek-r1:7b"}]}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        models = fetch_ollama_models("http://localhost:11434")
        assert models == ["llama3.2:latest", "deepseek-r1:7b"]


def test_check_ollama_status():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        online, msg = check_ollama_status("http://localhost:11434")
        assert not online
        assert "indisponível" in msg.lower()

    payload = json.dumps({"models": [{"name": "m1"}]}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        online, msg = check_ollama_status("http://localhost:11434")
        assert online
        assert "online" in msg.lower()


def test_settings_for_provider_openai():
    s = Settings(_env_file=None, openai_api_key="sk-test-key", llm_model="llama3.2", llm_base_url="http://localhost:11434/v1")
    s_openai = s.for_provider("openai", "gpt-4o")

    assert s_openai.llm_provider == "openai"
    assert s_openai.llm_model == "gpt-4o"
    assert s_openai.llm_base_url == "https://api.openai.com/v1"
    assert s_openai.effective_api_key == "sk-test-key"
    assert s_openai.llm_mode == "tools"
    assert s_openai.llm_context_tokens == 128_000
    assert s_openai.llm_timeout_s == 60.0


def test_settings_for_provider_ollama():
    s = Settings(_env_file=None, openai_api_key="sk-test-key", llm_model="gpt-4o-mini", llm_base_url="https://api.openai.com/v1")
    s_ollama = s.for_provider("ollama", "llama3.3:latest")

    assert s_ollama.llm_provider == "ollama"
    assert s_ollama.llm_model == "llama3.3:latest"
    assert s_ollama.llm_base_url == "http://localhost:11434/v1"
    assert s_ollama.effective_api_key == "ollama"
    assert s_ollama.llm_mode == "json"
    assert s_ollama.llm_context_tokens == 8192
    assert s_ollama.llm_timeout_s == 120.0


def test_job_manager_update_llm_config(make_deps):
    deps = make_deps(gateway=FakeLLMGateway())
    jm = JobManager(deps)
    try:
        assert jm.deps.settings.llm_model == "test-model"

        jm.update_llm_config(provider="openai", model="gpt-4o-mini", api_key="sk-test")
        assert jm.deps.settings.llm_model == "gpt-4o-mini"
        assert jm.deps.settings.llm_base_url == "https://api.openai.com/v1"

        jm.update_llm_config(provider="ollama", model="llama3.2")
        assert jm.deps.settings.llm_model == "llama3.2"
        assert jm.deps.settings.llm_base_url == "http://localhost:11434/v1"
    finally:
        jm.shutdown()
