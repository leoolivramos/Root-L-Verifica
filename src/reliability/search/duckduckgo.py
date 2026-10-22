"""DuckDuckGo provider via the `ddgs` package (no API key)."""

from __future__ import annotations

import asyncio
import re

from reliability.errors import SearchError
from reliability.search.base import SearchHit


class DuckDuckGoProvider:
    name = "duckduckgo"

    def __init__(self, *, region: str = "wt-wt", retries: int = 3, backoff_s: float = 1.5):
        self._region = region
        self._retries = retries
        self._backoff = backoff_s

    def _search_sync(self, query: str, max_results: int) -> list[dict]:
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException

        # Limpar aspas e espaços redundantes da query
        clean = re.sub(r'["“”\'\']', " ", query).strip()
        clean = re.sub(r"\s+", " ", clean)
        if not clean:
            return []

        # Tenta múltiplos backends suportados pela biblioteca ddgs:
        # 'auto' tenta os motores padrão; 'yahoo' busca pelo índice Yahoo/Bing; 'duckduckgo' direto
        backends = ["auto", "yahoo", "duckduckgo"]
        last_exc: Exception | None = None

        for b in backends:
            try:
                d = DDGS(timeout=10)
                rows = d.text(clean, region=self._region, backend=b, max_results=max_results)
                if rows:
                    return list(rows)
            except DDGSException as exc:
                last_exc = exc
                if "no results" in str(exc).lower():
                    continue
                continue
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue

        # Se todos os motores reportaram legitimamente ausência de resultados, retorna lista vazia
        if last_exc and "no results" in str(last_exc).lower():
            return []
        if last_exc is not None:
            raise last_exc
        return []

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                rows = await asyncio.to_thread(self._search_sync, query, max_results)
                return [
                    SearchHit(
                        url=r.get("href") or r.get("url") or "",
                        title=r.get("title") or "",
                        snippet=r.get("body") or "",
                    )
                    for r in rows
                    if (r.get("href") or r.get("url"))
                ]
            except Exception as exc:  # noqa: BLE001 - ddgs raises various rate-limit errors
                last = exc
                await asyncio.sleep(self._backoff * (2**attempt))
        raise SearchError(
            f"A busca no DuckDuckGo falhou (possível limite de requisições): {type(last).__name__}."
        )
