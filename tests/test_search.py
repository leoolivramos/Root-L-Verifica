"""Search providers and provider selection."""

from __future__ import annotations

import httpx
import pytest

from reliability.config import Settings
from reliability.errors import SearchError
from reliability.search.duckduckgo import DuckDuckGoProvider
from reliability.search.factory import make_search_provider
from reliability.search.tavily import TavilyProvider


def test_factory_selection():
    def s(**kw):
        return Settings(_env_file=None, **kw)

    assert isinstance(make_search_provider(s()), DuckDuckGoProvider)
    assert isinstance(make_search_provider(s(tavily_api_key="k")), TavilyProvider)
    assert isinstance(make_search_provider(s(tavily_api_key="k", search_provider="duckduckgo")), DuckDuckGoProvider)
    with pytest.raises(ValueError):
        make_search_provider(s(search_provider="tavily"))


async def test_tavily_parses_results():
    def handler(req):
        assert req.headers["authorization"] == "Bearer k"
        return httpx.Response(
            200,
            json={"results": [
                {"url": "https://a.com/x", "title": "A", "content": "snip", "published_date": "2026-01-02T00:00:00"},
                {"title": "sem url"},
            ]},
        )

    p = TavilyProvider("k", transport=httpx.MockTransport(handler))
    hits = await p.search("q", 3)
    assert len(hits) == 1 and hits[0].snippet == "snip" and hits[0].published_at.year == 2026


async def test_tavily_retries_rate_limit_then_fails_and_bad_key():
    n = {"c": 0}

    def limited(req):
        n["c"] += 1
        return httpx.Response(429)

    p = TavilyProvider("k", retries=3, backoff_s=0.0, transport=httpx.MockTransport(limited))
    with pytest.raises(SearchError):
        await p.search("q", 3)
    assert n["c"] == 3
    bad = TavilyProvider("k", transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(SearchError, match="inválida"):
        await bad.search("q", 3)


async def test_duckduckgo_backoff_and_mapping(monkeypatch):
    p = DuckDuckGoProvider(retries=3, backoff_s=0.0)
    calls = {"n": 0}

    def flaky(query, max_results):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("ratelimit")
        return [{"href": "https://a.com", "title": "T", "body": "B"}, {"title": "no href"}]

    monkeypatch.setattr(p, "_search_sync", flaky)
    hits = await p.search("q", 3)
    assert calls["n"] == 3 and [h.url for h in hits] == ["https://a.com"]

    monkeypatch.setattr(p, "_search_sync", lambda q, n: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(SearchError):
        await p.search("q", 3)
