"""LLM gateway: structured output via instructor against an OpenAI-compatible endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from reliability.errors import LLMUnavailable, StructuredOutputError

T = TypeVar("T", bound=BaseModel)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens


class LLMGateway(Protocol):
    async def structured(
        self, response_model: type[T], *, system: str, user: str, source_text: str
    ) -> tuple[T, Usage]:
        """Return a validated `response_model`. `source_text` is the text that any
        `exact_quote`/`source_quote` field must literally appear in (validator context).

        Raises StructuredOutputError (after retries) or LLMUnavailable.
        """
        ...

    async def analyze_image(
        self, image_bytes: bytes, mime_type: str = "image/jpeg", prompt: str = ""
    ) -> tuple[str, Usage]:
        """Analyze an image using multimodal vision capability."""
        ...

    async def analyze_frames(
        self, frames: list[bytes], prompt: str = ""
    ) -> tuple[str, Usage]:
        """Analyze sequential video keyframes using multimodal vision capability."""
        ...


class InstructorGateway:
    """Calls the model through `instructor` with automatic corrective retries."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        mode: str = "auto",
    ):
        import instructor
        from openai import AsyncOpenAI

        self._model = model
        self._max_retries = max_retries
        self._base_url = (base_url or "").strip()
        self._timeout_s = timeout_s

        is_openai = (
            not self._base_url
            or "api.openai.com" in self._base_url
            or model.lower().startswith(("gpt-", "o1", "o3", "chatgpt-"))
        )

        mode_str = mode.lower().strip()
        if mode_str == "tools" or (mode_str == "auto" and is_openai):
            chosen_mode = instructor.Mode.TOOLS
        elif mode_str == "json_schema":
            chosen_mode = instructor.Mode.JSON_SCHEMA
        else:
            chosen_mode = instructor.Mode.JSON

        # Avoid OpenAI client crash on empty key if not yet set
        effective_key = (
            api_key.strip()
            if api_key and api_key.strip()
            else ("ollama" if "localhost" in self._base_url else "missing-key")
        )

        client_kwargs: dict[str, Any] = {
            "api_key": effective_key,
            "timeout": timeout_s,
            "max_retries": 0,
        }
        if self._base_url:
            client_kwargs["base_url"] = self._base_url

        self._client = instructor.from_openai(
            AsyncOpenAI(**client_kwargs),
            mode=chosen_mode,
        )

    async def structured(
        self, response_model: type[T], *, system: str, user: str, source_text: str
    ) -> tuple[T, Usage]:
        import openai
        from instructor.core.hooks import Hooks

        usage = Usage()

        def _on_response(response) -> None:
            u = getattr(response, "usage", None)
            if u is not None:
                usage.prompt_tokens += getattr(u, "prompt_tokens", 0) or 0
                usage.completion_tokens += getattr(u, "completion_tokens", 0) or 0

        hooks = Hooks()
        hooks.on("completion:response", _on_response)

        is_reasoning_model = any(k in self._model.lower() for k in ("luna", "o1", "o3", "o4"))
        create_kwargs: dict[str, Any] = {
            "model": self._model,
            "response_model": response_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_retries": self._max_retries,
            "context": {"source_text": source_text},
            "hooks": hooks,
        }
        if is_reasoning_model:
            create_kwargs["reasoning_effort"] = "none"
        else:
            create_kwargs["temperature"] = 0

        try:
            result = await self._client.chat.completions.create(**create_kwargs)
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise LLMUnavailable(
                f"Tempo limite ou falha de conexão com o modelo em {self._base_url or 'OpenAI'}. "
                "Verifique sua conexão com a internet ou se o serviço está acessível."
            ) from exc
        except openai.AuthenticationError as exc:
            raise LLMUnavailable(
                "Chave de API inválida ou ausente (HTTP 401). "
                "Defina a variável OPENAI_API_KEY no arquivo .env com sua chave da OpenAI."
            ) from exc
        except openai.RateLimitError as exc:
            raise LLMUnavailable(
                "Limite de requisições ou créditos esgotados na OpenAI (HTTP 429). "
                "Verifique seu saldo ou limite de uso na sua conta OpenAI."
            ) from exc
        except openai.APIStatusError as exc:
            raise LLMUnavailable(
                f"O servidor do modelo respondeu com erro HTTP {exc.status_code}. "
                f"Confirme se o modelo '{self._model}' está disponível."
            ) from exc
        except Exception as exc:
            from instructor.core import InstructorRetryException

            cause = getattr(exc, "__cause__", None) or exc
            if isinstance(cause, openai.AuthenticationError):
                raise LLMUnavailable(
                    "Chave de API inválida ou ausente (HTTP 401). "
                    "Defina a variável OPENAI_API_KEY no arquivo .env com sua chave da OpenAI."
                ) from exc
            if isinstance(cause, openai.RateLimitError):
                raise LLMUnavailable(
                    "Limite de requisições ou créditos esgotados na OpenAI (HTTP 429). "
                    "Verifique seu saldo ou limite de uso na sua conta OpenAI."
                ) from exc
            if (
                isinstance(cause, (openai.APITimeoutError, TimeoutError))
                or "timed out" in str(cause).lower()
            ):
                raise LLMUnavailable(
                    f"Tempo limite esgotado ({self._timeout_s:.0f}s) aguardando o modelo '{self._model}'. "
                    "Tente novamente ou aumente LLM_TIMEOUT_S no arquivo .env."
                ) from exc
            if isinstance(cause, openai.APIConnectionError):
                raise LLMUnavailable(
                    f"Não foi possível conectar ao endpoint {self._base_url or 'OpenAI'}. "
                    "Verifique sua conexão de rede ou se o serviço está em execução."
                ) from exc
            if isinstance(cause, openai.APIStatusError):
                raise LLMUnavailable(
                    f"O servidor do modelo respondeu com erro HTTP {cause.status_code}. "
                    f"Confirme se o modelo '{self._model}' está disponível."
                ) from exc

            if isinstance(exc, InstructorRetryException):
                for attempt in getattr(exc, "failed_attempts", []) or []:
                    sub = getattr(attempt, "exception", None)
                    if (
                        isinstance(sub, (openai.APITimeoutError, TimeoutError))
                        or "timed out" in str(sub).lower()
                    ):
                        raise LLMUnavailable(
                            f"Tempo limite esgotado ({self._timeout_s:.0f}s) aguardando o modelo '{self._model}'."
                        ) from exc
                    if isinstance(sub, openai.APIConnectionError):
                        raise LLMUnavailable(
                            f"Não foi possível conectar ao modelo em {self._base_url or 'OpenAI'}."
                        ) from exc

            raise StructuredOutputError(
                f"O modelo não retornou uma resposta estruturada válida após "
                f"{self._max_retries} tentativas ({type(exc).__name__}).",
                usage.prompt_tokens,
                usage.completion_tokens,
            ) from exc
        return result, usage

    async def analyze_image(
        self, image_bytes: bytes, mime_type: str = "image/jpeg", prompt: str = ""
    ) -> tuple[str, Usage]:
        import base64

        import openai

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        usage = Usage()
        is_reasoning_model = any(k in self._model.lower() for k in ("luna", "o1", "o3", "o4"))
        create_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
        }
        if is_reasoning_model:
            create_kwargs["reasoning_effort"] = "none"
            create_kwargs["max_completion_tokens"] = 2500
        else:
            create_kwargs["temperature"] = 0
            create_kwargs["max_tokens"] = 2500

        raw_client = getattr(self._client, "client", self._client)
        try:
            resp = await raw_client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            cause = getattr(exc, "__cause__", None) or exc
            if isinstance(cause, openai.AuthenticationError):
                raise LLMUnavailable(
                    "Chave de API inválida ou ausente (HTTP 401). "
                    "Defina a variável OPENAI_API_KEY no arquivo .env."
                ) from exc
            if (
                isinstance(cause, (openai.APITimeoutError, TimeoutError))
                or "timed out" in str(cause).lower()
            ):
                raise LLMUnavailable(
                    f"Tempo limite esgotado ({self._timeout_s:.0f}s) aguardando análise visual do modelo '{self._model}'."
                ) from exc
            raise LLMUnavailable(f"Erro na análise visual da imagem: {cause}") from exc

        u = getattr(resp, "usage", None)
        if u:
            usage.prompt_tokens += getattr(u, "prompt_tokens", 0) or 0
            usage.completion_tokens += getattr(u, "completion_tokens", 0) or 0
        content = resp.choices[0].message.content or ""
        return content, usage

    async def analyze_frames(
        self, frames: list[bytes], prompt: str = ""
    ) -> tuple[str, Usage]:
        import base64

        import openai

        usage = Usage()
        content_items: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for f_bytes in frames:
            b64 = base64.b64encode(f_bytes).decode("utf-8")
            content_items.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "high",
                },
            })

        is_reasoning_model = any(k in self._model.lower() for k in ("luna", "o1", "o3", "o4"))
        create_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": content_items}],
        }
        if is_reasoning_model:
            create_kwargs["reasoning_effort"] = "none"
            create_kwargs["max_completion_tokens"] = 2500
        else:
            create_kwargs["temperature"] = 0
            create_kwargs["max_tokens"] = 2500

        raw_client = getattr(self._client, "client", self._client)
        try:
            resp = await raw_client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            cause = getattr(exc, "__cause__", None) or exc
            if isinstance(cause, openai.AuthenticationError):
                raise LLMUnavailable(
                    "Chave de API inválida ou ausente (HTTP 401). "
                    "Defina a variável OPENAI_API_KEY no arquivo .env."
                ) from exc
            if (
                isinstance(cause, (openai.APITimeoutError, TimeoutError))
                or "timed out" in str(cause).lower()
            ):
                raise LLMUnavailable(
                    f"Tempo limite esgotado ({self._timeout_s:.0f}s) aguardando análise dos frames pelo modelo '{self._model}'."
                ) from exc
            raise LLMUnavailable(f"Erro na análise visual dos frames do vídeo: {cause}") from exc

        u = getattr(resp, "usage", None)
        if u:
            usage.prompt_tokens += getattr(u, "prompt_tokens", 0) or 0
            usage.completion_tokens += getattr(u, "completion_tokens", 0) or 0
        content = resp.choices[0].message.content or ""
        return content, usage
