"""Evidence gathering for one claim: search → fetch/snippet → LLM judgement → verified quote."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime

from reliability.claims.judge_evidence import judge_evidence
from reliability.claims.llm import LLMGateway, Usage
from reliability.errors import (
    FetchError,
    ReliabilityError,
    SearchError,
    StructuredOutputError,
    UnsafeURL,
)
from reliability.extraction.blockers import detect_blockers
from reliability.extraction.extractor import extract_document, registrable_domain
from reliability.extraction.fetcher import SafeFetcher
from reliability.schemas import Depth, EvidenceJudgement, Stance, quote_in_text
from reliability.search.base import EvidenceSearchProvider, SearchHit

RESULTS_PER_CLAIM = {Depth.FAST: 3, Depth.DEEP: 5}
PASSAGE_CHARS = {Depth.FAST: 2500, Depth.DEEP: 4500}


@dataclass
class SourceInfo:
    url: str
    title: str | None
    publisher: str | None
    domain: str | None
    published_at: datetime | None
    is_paywalled: bool


@dataclass
class GatheredEvidence:
    source: SourceInfo
    judgement: EvidenceJudgement


_WORD_RE = re.compile(r"\w{4,}", re.UNICODE)


def select_passage(text: str, claim_text: str, max_chars: int) -> str:
    """Deterministically pick the paragraphs most related to the claim (keyword overlap),
    preserving original order, within `max_chars`."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    paras = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?])\s{2,}", text) if p.strip()]
    if not paras:
        return text[:max_chars]
    keys = set(w.lower() for w in _WORD_RE.findall(claim_text))
    scored = []
    for i, p in enumerate(paras):
        words = set(w.lower() for w in _WORD_RE.findall(p))
        scored.append((len(keys & words), -i, i, p))
    scored.sort(reverse=True)
    chosen: list[tuple[int, str]] = []
    used = 0
    for _, _, i, p in scored:
        if used + len(p) > max_chars:
            if not chosen:  # a single huge paragraph: cut it
                chosen.append((i, p[:max_chars]))
            continue
        chosen.append((i, p))
        used += len(p) + 2
    chosen.sort()
    return "\n\n".join(p for _, p in chosen)


async def _passage_for_hit(
    hit: SearchHit, claim_text: str, depth: Depth, fetcher: SafeFetcher, warnings: list[str]
) -> tuple[str, bool, SourceInfo]:
    domain = registrable_domain(hit.url)
    title, publisher, published, paywalled = hit.title or None, None, hit.published_at, False
    text = (hit.raw_content or hit.snippet or "").strip()

    if depth is Depth.DEEP:
        try:
            fetched = await fetcher.fetch(hit.url)
            doc = extract_document(fetched.text, fetched.url)
            if len(doc.text) >= 200:
                text = doc.text
            paywalled = any(b.kind == "paywall" for b in doc.blockers)
            title = doc.title or title
            publisher = doc.publisher
            published = doc.published_at or published
        except (FetchError, UnsafeURL) as exc:
            warnings.append(
                f"Não foi possível abrir {domain} ({exc}); usado apenas o trecho da busca."
            )
    elif text:
        paywalled = any(b.kind == "paywall" for b in detect_blockers("", text) if b.blocking)

    info = SourceInfo(hit.url, title, publisher, domain, published, paywalled)
    return select_passage(text, claim_text, PASSAGE_CHARS[depth]), paywalled, info


async def gather_evidence(
    *,
    claim_text: str,
    query: str,
    provider: EvidenceSearchProvider,
    fetcher: SafeFetcher,
    gateway: LLMGateway,
    depth: Depth,
    exclude_domain: str | None,
    usage: Usage,
    warnings: list[str],
    semaphore: asyncio.Semaphore,
) -> list[GatheredEvidence]:
    try:
        async with semaphore:
            hits = await provider.search(query, RESULTS_PER_CLAIM[depth] + 2)
    except SearchError as exc:
        warnings.append(f"Falha na busca para uma alegação: {exc}")
        return []

    chosen: list[SearchHit] = []
    seen_domains: set[str] = set()
    for h in hits:
        d = registrable_domain(h.url)
        if not d or d == exclude_domain or d in seen_domains:
            continue
        seen_domains.add(d)
        chosen.append(h)
        if len(chosen) >= RESULTS_PER_CLAIM[depth]:
            break

    async def one(hit: SearchHit) -> GatheredEvidence | None:
        async with semaphore:
            passage, _, info = await _passage_for_hit(hit, claim_text, depth, fetcher, warnings)
            if len(passage) < 30:
                return None
            try:
                judgement, u = await judge_evidence(gateway, claim_text, passage)
            except StructuredOutputError as exc:
                usage.add(Usage(exc.prompt_tokens, exc.completion_tokens))
                warnings.append(f"Não foi possível julgar a fonte {info.domain}: {exc}")
                return None
            except ReliabilityError:
                raise
            usage.add(u)
            if judgement.stance is Stance.NEUTRAL:
                return None
            if not quote_in_text(judgement.exact_quote, passage):
                return None  # defensive: never persist an unverifiable quote
            return GatheredEvidence(info, judgement)

    results = await asyncio.gather(*(one(h) for h in chosen))
    return [r for r in results if r is not None]
