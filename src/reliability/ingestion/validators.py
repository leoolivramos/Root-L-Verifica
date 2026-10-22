"""Input parsing and validation (RF-01..RF-03)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from reliability.errors import InvalidInput

_URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
MIN_TEXT_CHARS = 40


@dataclass(frozen=True)
class ValidatedInput:
    kind: Literal["url", "text"]
    value: str


def parse_input(raw: str | None, max_chars: int = 200_000) -> ValidatedInput:
    """Classify `raw` as URL or text, validating shape and size (not network safety)."""
    if raw is None or not raw.strip():
        raise InvalidInput("Informe uma URL ou cole um texto para analisar.")
    value = raw.strip()

    single_token = not re.search(r"\s", value)
    if single_token and (_URL_RE.match(value) or "://" in value):
        if value.lower().startswith("www."):
            value = "https://" + value
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https"):
            raise InvalidInput(
                f"Esquema '{parts.scheme}://' não suportado. Use uma URL http:// ou https://."
            )
        if not parts.hostname:
            raise InvalidInput("A URL informada não possui um host válido.")
        if parts.username or parts.password:
            raise InvalidInput("URLs com credenciais embutidas não são aceitas.")
        if len(value) > 2048:
            raise InvalidInput("A URL é longa demais (máx. 2048 caracteres).")
        return ValidatedInput("url", value)

    if len(value) < MIN_TEXT_CHARS:
        raise InvalidInput(
            f"Texto muito curto (mínimo {MIN_TEXT_CHARS} caracteres). "
            "Cole um trecho maior ou informe uma URL completa."
        )
    if len(value) > max_chars:
        raise InvalidInput(f"Texto grande demais (máx. {max_chars:,} caracteres).".replace(",", "."))
    return ValidatedInput("text", value)
