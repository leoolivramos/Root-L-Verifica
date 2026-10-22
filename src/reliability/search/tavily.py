"""Tavily provider (REST API via httpx)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

from reliability.errors import SearchError
from reliability.search.base import SearchHit

TAVILY_URL = "https://api.tavily.com/search"


class TavilyProvider:
    name = "tavily"

    def __init__(
        self,
        api_key: str,
        *,
        retries: int = 3,
        backoff_s: float = 1.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._key = api_key
        self._retries = retries
        self._backoff = backoff_s
        self._transport = transport

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        payload = {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        last = "erro desconhecido"
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as client:
            for attempt in range(self._retries):
                try:
                    resp = await client.post(TAVILY_URL, json=payload, headers=headers)
                    if resp.status_code in (401, 403):
                        raise SearchError("Chave da Tavily inválida ou sem permissão.")
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last = f"HTTP {resp.status_code}"
                        await asyncio.sleep(self._backoff * (2**attempt))
                        continue
                    resp.raise_for_status()
                    return [self._hit(r) for r in resp.json().get("results", []) if r.get("url")]
                except SearchError:
                    raise
                except (httpx.HTTPError, ValueError) as exc:
                    last = type(exc).__name__
                    await asyncio.sleep(self._backoff * (2**attempt))
        raise SearchError(f"A busca na Tavily falhou ({last}).")

    @staticmethod
    def _hit(r: dict) -> SearchHit:
        published = None
        if r.get("published_date"):
            try:
                published = datetime.fromisoformat(str(r["published_date"])[:19])
            except ValueError:
                published = None
        return SearchHit(
            url=r["url"],
            title=r.get("title") or "",
            snippet=r.get("content") or "",
            published_at=published,
            raw_content=r.get("raw_content"),
        )
