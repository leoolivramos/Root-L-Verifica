"""Context-window truncation (RF-04.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from reliability.config import CHARS_PER_TOKEN


@dataclass(frozen=True)
class TruncationInfo:
    truncated: bool
    original_chars: int
    kept_chars: int

    @property
    def removed_pct(self) -> int:
        if not self.original_chars:
            return 0
        return round(100 * (self.original_chars - self.kept_chars) / self.original_chars)

    def warning(self) -> str | None:
        if not self.truncated:
            return None
        return (
            f"O texto excedia a janela de contexto do modelo e foi truncado: "
            f"~{self.removed_pct}% do conteúdo (parte central) não foi analisado."
        )


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _cut_start(text: str, limit: int) -> str:
    head = text[:limit]
    # prefer paragraph, then sentence boundary, within the last 25% of the window
    floor = int(limit * 0.75)
    for pattern in ("\n\n", r"[.!?]\s"):
        idxs = [m.end() for m in re.finditer(pattern, head) if m.end() >= floor]
        if idxs:
            return head[: idxs[-1]].rstrip()
    return head.rstrip()


def _cut_end(text: str, limit: int) -> str:
    tail = text[-limit:]
    ceil = int(limit * 0.25)
    for pattern in ("\n\n", r"[.!?]\s"):
        idxs = [m.end() for m in re.finditer(pattern, tail) if m.end() <= ceil]
        if idxs:
            return tail[idxs[0] :].lstrip()
    return tail.lstrip()


def fit_to_context(text: str, budget_tokens: int) -> tuple[str, TruncationInfo]:
    """Fit `text` into `budget_tokens`, keeping the beginning (70%) and the end (30%)."""
    max_chars = max(200, int(budget_tokens * CHARS_PER_TOKEN))
    if len(text) <= max_chars:
        return text, TruncationInfo(False, len(text), len(text))
    marker = "\n\n[... trecho intermediário omitido ...]\n\n"
    usable = max_chars - len(marker)
    head = _cut_start(text, int(usable * 0.7))
    tail = _cut_end(text, usable - len(head))
    out = head + marker + tail
    return out, TruncationInfo(True, len(text), len(head) + len(tail))
