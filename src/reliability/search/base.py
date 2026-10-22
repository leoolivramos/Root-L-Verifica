"""Search provider contract (RF-07)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str
    published_at: datetime | None = None
    raw_content: str | None = None


class EvidenceSearchProvider(Protocol):
    name: str

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        """Return up to `max_results` hits. Raises SearchError on failure."""
        ...
