"""Dependency wiring (real vs. demo mode)."""

from __future__ import annotations

from reliability.config import Settings
from reliability.extraction.fetcher import SafeFetcher
from reliability.persistence.db import make_engine, make_session_factory
from reliability.persistence.repository import AnalysisRepository
from reliability.pipeline import Deps


def build_deps(settings: Settings) -> Deps:
    repo = AnalysisRepository(make_session_factory(make_engine(settings.db_file)))
    if settings.reliability_demo:
        from reliability.demo import DemoFetcher, FakeLLMGateway, FakeSearchProvider

        return Deps(
            settings=settings,
            gateway=FakeLLMGateway(delay_s=0.4),
            provider=FakeSearchProvider(),
            fetcher=DemoFetcher(),  # type: ignore[arg-type]
            repo=repo,
        )

    from reliability.claims.llm import InstructorGateway
    from reliability.search.factory import make_search_provider

    return Deps(
        settings=settings,
        gateway=InstructorGateway(
            base_url=settings.llm_base_url,
            api_key=settings.effective_api_key,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
            mode=settings.llm_mode,
        ),
        provider=make_search_provider(settings),
        fetcher=SafeFetcher(
            max_bytes=settings.fetch_max_bytes,
            timeout_s=settings.fetch_timeout_s,
            max_redirects=settings.fetch_max_redirects,
            allowed_ports=settings.allowed_ports,
        ),
        repo=repo,
    )
