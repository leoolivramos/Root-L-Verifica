"""Shared fixtures."""

from __future__ import annotations

import httpx
import pytest

from reliability.config import Settings
from reliability.demo import FakeLLMGateway, FakeSearchProvider
from reliability.extraction.fetcher import SafeFetcher
from reliability.persistence.db import make_engine, make_session_factory
from reliability.persistence.repository import AnalysisRepository
from reliability.pipeline import Deps


@pytest.fixture
def repo() -> AnalysisRepository:
    return AnalysisRepository(make_session_factory(make_engine(":memory:")))


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, db_path=":memory:", llm_model="test-model")


async def _public_resolver(url: str) -> list[str]:
    return ["93.184.216.34"]


def make_fetcher(handler=None) -> SafeFetcher:
    """SafeFetcher over a MockTransport with a stub resolver (no DNS, no network)."""
    handler = handler or (lambda req: httpx.Response(404))
    return SafeFetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)


@pytest.fixture
def make_deps(repo, settings):
    def _make(gateway=None, provider=None, fetcher=None) -> Deps:
        return Deps(
            settings=settings,
            gateway=gateway or FakeLLMGateway(),
            provider=provider or FakeSearchProvider(),
            fetcher=fetcher or make_fetcher(),
            repo=repo,
        )

    return _make
