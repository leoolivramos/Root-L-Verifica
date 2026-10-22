"""Domain errors with user-facing (pt-BR) messages."""

from __future__ import annotations


class ReliabilityError(Exception):
    """Base class; `str(e)` is safe to show to the user."""


class InvalidInput(ReliabilityError):
    pass


class UnsafeURL(ReliabilityError):
    """URL blocked by SSRF protection."""


class FetchError(ReliabilityError):
    pass


class ExtractionBlocked(ReliabilityError):
    """The page only exposed a cookie wall / paywall, no analysable content."""


class StructuredOutputError(ReliabilityError):
    """LLM failed to return valid structured output after all retries."""

    def __init__(self, message: str, prompt_tokens: int = 0, completion_tokens: int = 0):
        super().__init__(message)
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class LLMUnavailable(ReliabilityError):
    """Could not reach the configured LLM endpoint."""


class SearchError(ReliabilityError):
    pass
