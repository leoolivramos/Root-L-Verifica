"""End-to-end pipeline runs with fake LLM / search / network."""

from __future__ import annotations

import httpx

from reliability.demo import FakeLLMGateway, FakeSearchProvider
from reliability.errors import LLMUnavailable, SearchError
from reliability.pipeline import create_analysis, run_analysis
from reliability.schemas import (
    AnalysisStatus,
    ClaimVerdict,
    Depth,
    EvidenceJudgement,
    ExtractionResult,
    OverallStatus,
    TagCode,
)
from reliability.search.base import SearchHit
from tests.conftest import make_fetcher
from tests.test_extraction import ARTICLE, COOKIE_WALL, PAYWALL

CLAIM = "O PIB do país cresceu 2,9% em 2025 segundo o instituto oficial de estatística."
TEXT = CLAIM + " Isso foi um grande sucesso para todos os brasileiros e brasileiras."
QUERY = "pib 2025 crescimento ibge"


def script(claims, emo=(), opi=()):
    def handler(model, system, user, source_text):
        if model is ExtractionResult:
            return [
                {
                    "summary": "Resumo curto.",
                    "claims": claims,
                    "emotional_quotes": list(emo),
                    "assertive_opinion_quotes": list(opi),
                }
            ]
        if model is EvidenceJudgement:
            low = source_text.lower()
            quote = source_text.strip().split(".")[0].strip() + "."
            stance = (
                "contradicts" if "desmente" in low
                else "partially_supports" if "em parte" in low
                else "supports"
            )
            return [{"stance": stance, "relevance": 0.9, "exact_quote": quote, "omits_context": False}]
        return []

    return handler


def claim(text=CLAIM, ctype="quantitative_fact", query=QUERY, **kw):
    return {
        "text": text,
        "claim_type": ctype,
        "verification_query": query,
        "requires_external_evidence": True,
        "source_quote": text,
        **kw,
    }


def hits(*bodies):
    return [
        SearchHit(url=f"https://site{i}.org/n", title=f"T{i}", snippet=b)
        for i, b in enumerate(bodies)
    ]


async def _run(deps, raw=TEXT, depth=Depth.FAST):
    aid = create_analysis(deps, raw, depth)
    await run_analysis(aid, deps)
    return deps.repo.get_report(aid), aid


async def test_text_well_corroborated_and_telemetry(make_deps):
    prov = FakeSearchProvider(
        {QUERY: hits("O instituto confirma o crescimento de 2,9% do PIB. Detalhes.",
                     "Relatório confirma a alta do PIB em 2025. Mais.")}
    )
    deps = make_deps(gateway=FakeLLMGateway(script([claim()])), provider=prov)
    rep, aid = await _run(deps)
    assert rep.status is AnalysisStatus.COMPLETED
    assert rep.overall_status is OverallStatus.WELL_CORROBORATED
    c = rep.claims[0]
    assert c.verification_status is ClaimVerdict.CORROBORATED and c.rationale.startswith("Regra 6")
    assert len(c.evidences) == 2 and all(e.exact_quote for e in c.evidences)
    assert TagCode.ORIGEM_NAO_CONFIRMADA in {t.code for t in rep.tags}
    # telemetry + versions (RF-13, RNF-07)
    assert rep.prompt_tokens > 0 and rep.completion_tokens > 0 and rep.processing_time_ms >= 0
    assert rep.model_name == "test-model" and rep.pipeline_version and rep.prompt_version
    assert rep.summary == "Resumo curto."
    steps = [e[1] for e in deps.repo.list_events(aid)]
    assert {"EXTRACTING", "INVESTIGATING", "CLASSIFYING", "COMPLETED"} <= set(steps)


async def test_contradiction_dominates(make_deps):
    prov = FakeSearchProvider({QUERY: hits("A checagem desmente o dado do PIB. Falso.")})
    deps = make_deps(gateway=FakeLLMGateway(script([claim()])), provider=prov)
    rep, _ = await _run(deps)
    assert rep.overall_status is OverallStatus.CONTRADICTED
    assert rep.claims[0].verification_status is ClaimVerdict.CONTRADICTED
    assert TagCode.CONTRADICAO_ENCONTRADA in {t.code for t in rep.claims[0].tags}


async def test_opinions_are_not_searched(make_deps):
    prov = FakeSearchProvider()
    opinion = claim("Este governo é o melhor que o país já teve na história.", "opinion")
    deps = make_deps(gateway=FakeLLMGateway(script([opinion])), provider=prov)
    rep, _ = await _run(deps, "Este governo é o melhor que o país já teve na história. " + "x" * 20)
    assert prov.queries == []
    assert rep.claims[0].verification_status is ClaimVerdict.NOT_VERIFIABLE
    assert rep.overall_status is OverallStatus.INSUFFICIENT


async def test_url_paywall_is_partial_with_warning(make_deps):
    fetcher = make_fetcher(lambda r: httpx.Response(200, text=PAYWALL, headers={"content-type": "text/html"}))
    deps = make_deps(fetcher=fetcher)
    rep, _ = await _run(deps, "https://example.com/especial")
    assert rep.status is AnalysisStatus.PARTIAL
    assert any("paywall" in w.lower() for w in rep.warnings)


async def test_url_cookie_wall_fails_gracefully(make_deps):
    fetcher = make_fetcher(lambda r: httpx.Response(200, text=COOKIE_WALL, headers={"content-type": "text/html"}))
    rep, _ = await _run(make_deps(fetcher=fetcher), "https://example.com/n")
    assert rep.status is AnalysisStatus.FAILED
    assert "cookies" in rep.error_message.lower()


async def test_url_pipeline_with_metadata(make_deps):
    fetcher = make_fetcher(lambda r: httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"}))
    rep, _ = await _run(make_deps(fetcher=fetcher), "https://www.jornalexemplo.com.br/economia/cresce")
    assert rep.title and rep.domain == "jornalexemplo.com.br"
    assert rep.status in {AnalysisStatus.COMPLETED, AnalysisStatus.PARTIAL}
    assert TagCode.FONTE_NAO_IDENTIFICADA not in {t.code for t in rep.tags}


async def test_ssrf_url_fails_without_any_request(make_deps):
    from reliability.extraction.fetcher import SafeFetcher

    calls = []
    fetcher = SafeFetcher(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
    rep, _ = await _run(make_deps(fetcher=fetcher), "http://169.254.169.254/latest/meta-data/")
    assert rep.status is AnalysisStatus.FAILED and "bloqueado" in rep.error_message.lower()
    assert calls == []


async def test_llm_structured_failure_is_graceful_and_counts_tokens(make_deps):
    gw = FakeLLMGateway(lambda *a: ["prosa", "prosa", "prosa"])
    rep, _ = await _run(make_deps(gateway=gw))
    assert rep.status is AnalysisStatus.FAILED
    assert "estruturada" in rep.error_message
    assert rep.prompt_tokens > 0


async def test_search_failure_marks_partial(make_deps):
    class Boom:
        name = "boom"

        async def search(self, q, n):
            raise SearchError("limite de requisições")

    deps = make_deps(gateway=FakeLLMGateway(script([claim()])), provider=Boom())
    rep, _ = await _run(deps)
    assert rep.status is AnalysisStatus.PARTIAL
    assert any("limite" in w for w in rep.warnings)
    assert rep.claims[0].verification_status is ClaimVerdict.INCONCLUSIVE


async def test_llm_down_during_judging_marks_partial(make_deps):
    inner = FakeLLMGateway(script([claim()]))

    class Flaky:
        async def structured(self, model, **kw):
            if model is EvidenceJudgement:
                raise LLMUnavailable("modelo caiu")
            return await inner.structured(model, **kw)

    prov = FakeSearchProvider({QUERY: hits("O instituto confirma o dado. x")})
    rep, _ = await _run(make_deps(gateway=Flaky(), provider=prov))
    assert rep.status is AnalysisStatus.PARTIAL
    assert any("caiu" in w for w in rep.warnings)


async def test_long_input_is_truncated_with_warning(make_deps):
    deps = make_deps()
    deps.settings.llm_context_tokens = 3000  # → ~1000 tokens for the document
    long_text = " ".join(f"A cidade {i} registrou {i + 10} casos no relatório oficial de 2025." for i in range(900))
    rep, _ = await _run(deps, long_text)
    assert rep.status is AnalysisStatus.PARTIAL
    assert any("truncado" in w for w in rep.warnings)


async def test_deep_mode_fetches_source_pages(make_deps):
    page = (
        "<html><head><title>Página da fonte</title></head><body><article><p>"
        + "O instituto confirma o crescimento de 2,9% do PIB em 2025. " * 12
        + "</p></article></body></html>"
    )
    seen = []

    def handler(req):
        seen.append(req.url.host)
        return httpx.Response(200, text=page, headers={"content-type": "text/html"})

    prov = FakeSearchProvider({QUERY: hits("snippet curto", "outro snippet")})
    deps = make_deps(gateway=FakeLLMGateway(script([claim()])), provider=prov, fetcher=make_fetcher(handler))
    rep, _ = await _run(deps, depth=Depth.DEEP)
    assert set(seen) == {"site0.org", "site1.org"}
    ev = rep.claims[0].evidences
    assert len(ev) == 2 and all(e.source_title == "Página da fonte" for e in ev)
    assert rep.depth is Depth.DEEP
