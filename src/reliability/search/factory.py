"""Provider selection from settings."""

from __future__ import annotations

from reliability.config import Settings
from reliability.search.base import EvidenceSearchProvider
from reliability.search.duckduckgo import DuckDuckGoProvider
from reliability.search.tavily import TavilyProvider


def make_search_provider(settings: Settings) -> EvidenceSearchProvider:
    choice = settings.search_provider.lower()
    if choice == "tavily" or (choice == "auto" and settings.tavily_api_key):
        if not settings.tavily_api_key:
            raise ValueError("SEARCH_PROVIDER=tavily exige TAVILY_API_KEY no .env.")
        return TavilyProvider(settings.tavily_api_key)
    return DuckDuckGoProvider()
