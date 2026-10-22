"""Async analysis orchestrator (the 9-step lifecycle)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

from reliability.claims.extract_claims import extract_claims
from reliability.claims.llm import LLMGateway, Usage
from reliability.config import PIPELINE_VERSION, PROMPT_VERSION, Settings
from reliability.errors import (
    ExtractionBlocked,
    FetchError,
    InvalidInput,
    LLMUnavailable,
    ReliabilityError,
    StructuredOutputError,
    UnsafeURL,
)
from reliability.extraction.extractor import (
    ExtractedDocument,
    document_from_text,
    extract_document,
)
from reliability.extraction.fetcher import SafeFetcher
from reliability.extraction.media import (
    extract_image_document,
    extract_video_document,
    extract_youtube_document,
    is_image_content,
    is_video_content,
    is_youtube_url,
)
from reliability.ingestion.truncation import fit_to_context
from reliability.ingestion.validators import parse_input
from reliability.persistence.repository import AnalysisRepository
from reliability.schemas import (
    NON_VERIFIABLE_TYPES,
    AnalysisStatus,
    Depth,
    Stance,
)
from reliability.search.base import EvidenceSearchProvider
from reliability.search.evidence import gather_evidence
from reliability.verification.overall import classify_overall
from reliability.verification.rules import ClaimFacts, EvidenceFact, evaluate_claim
from reliability.verification.tags import ClaimOutcome, DocFacts, assign_tags

log = logging.getLogger(__name__)

# Tokens reserved for system prompt + structured response when fitting the document.
EXTRACTION_RESERVED_TOKENS = 2500


@dataclass
class Deps:
    settings: Settings
    gateway: LLMGateway
    provider: EvidenceSearchProvider
    fetcher: SafeFetcher
    repo: AnalysisRepository


def create_analysis(deps: Deps, raw: str, depth: Depth) -> int:
    """Validate the raw input (raises InvalidInput) and create the PENDING record."""
    parsed = parse_input(raw, deps.settings.max_input_chars)
    return deps.repo.create_analysis(
        input_type=parsed.kind,
        original_input=parsed.value,
        depth=depth.value,
        pipeline_version=PIPELINE_VERSION,
        prompt_version=PROMPT_VERSION,
        model_name=deps.settings.llm_model,
        llm_base_url=deps.settings.llm_base_url,
    )


async def run_analysis(analysis_id: int, deps: Deps) -> None:
    t0 = perf_counter()
    usage = Usage()
    warnings: list[str] = []
    repo = deps.repo

    async def db(fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def step(status: AnalysisStatus, label: str) -> None:
        await db(repo.set_status, analysis_id, status, label)
        await db(repo.add_event, analysis_id, status.value, label)

    async def note(message: str) -> None:
        await db(repo.add_event, analysis_id, "INFO", message)

    async def flush_warnings() -> None:
        for w in warnings:
            await db(repo.add_warning, analysis_id, w)

    def elapsed_ms() -> int:
        return int((perf_counter() - t0) * 1000)

    async def fail(message: str) -> None:
        await flush_warnings()
        await db(
            repo.finalize,
            analysis_id,
            status=AnalysisStatus.FAILED,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            processing_time_ms=elapsed_ms(),
            error_message=message,
        )
        await db(repo.add_event, analysis_id, "FAILED", message)

    try:
        input_type, original, depth_s = await db(repo.get_input, analysis_id)
        depth = Depth(depth_s)

        # ------------------------------------------------ 2. safe extraction
        await step(AnalysisStatus.EXTRACTING, "Extraindo conteúdo")
        doc: ExtractedDocument
        if input_type == "url":
            if is_youtube_url(original):
                await note(f"Vídeo do YouTube identificado: {original}")
                doc = await extract_youtube_document(original)
            else:
                await note(f"Baixando {original}")
                try:
                    fetched = await deps.fetcher.fetch(original)
                except (UnsafeURL, FetchError) as exc:
                    return await fail(str(exc))
                if fetched.truncated:
                    warnings.append("O conteúdo era muito grande e foi lido só parcialmente.")

                if is_image_content(fetched.content_type, fetched.url):
                    await note("Imagem/Foto identificada. Executando análise visual e OCR (Vision)…")
                    doc = await extract_image_document(
                        deps.gateway, fetched.raw_bytes, fetched.content_type, fetched.url
                    )
                    usage.add(doc.metadata.get("usage", Usage()))
                elif is_video_content(fetched.content_type, fetched.url):
                    await note("Vídeo identificado. Amostrando frames e analisando conteúdo visual…")
                    doc = await extract_video_document(deps.gateway, fetched.raw_bytes, fetched.url)
                    usage.add(doc.metadata.get("usage", Usage()))
                else:
                    doc = await asyncio.to_thread(extract_document, fetched.text, fetched.url)
                    for b in doc.blockers:
                        warnings.append(b.detail)
                    if doc.is_unusable:
                        kinds = {b.kind for b in doc.blockers}
                        if "cookies" in kinds:
                            raise ExtractionBlocked(
                                "A página só exibiu um aviso de consentimento de cookies, sem conteúdo "
                                "analisável. Cole o texto do artigo manualmente."
                            )
                        if "paywall" in kinds:
                            raise ExtractionBlocked(
                                "O conteúdo está atrás de um paywall e nenhum texto aberto foi obtido. "
                                "Cole o texto do artigo manualmente."
                            )
                        raise ExtractionBlocked(
                            "Não foi possível extrair texto relevante desta página (pode depender de "
                            "JavaScript). Cole o texto manualmente."
                        )
        else:
            doc = document_from_text(original)

        await db(
            repo.update_meta,
            analysis_id,
            title=doc.title,
            domain=doc.domain,
            media_type=doc.media_type,
            media_url=doc.media_url,
        )
        media_badge = f" [{doc.media_type.upper()}]" if doc.media_type else ""
        await note(
            f"Conteúdo extraído{media_badge}: {len(doc.text):,} caracteres".replace(",", ".")
            + (f" — {doc.title}" if doc.title else "")
        )

        budget = max(1000, deps.settings.llm_context_tokens - EXTRACTION_RESERVED_TOKENS)
        text, trunc = fit_to_context(doc.text, budget)
        if (w := trunc.warning()) is not None:
            warnings.append(w)
            await note(w)

        # ------------------------------------------------ 3. claim extraction
        await step(AnalysisStatus.EXTRACTING, "Identificando alegações (LLM)")
        try:
            extraction, u = await extract_claims(deps.gateway, text, depth)
        except StructuredOutputError as exc:
            usage.add(Usage(exc.prompt_tokens, exc.completion_tokens))
            return await fail(str(exc))
        except LLMUnavailable as exc:
            return await fail(str(exc))
        usage.add(u)
        await db(repo.update_meta, analysis_id, summary=extraction.summary or None)
        await note(f"{len(extraction.claims)} alegação(ões) identificada(s)")

        claim_ids: list[int] = []
        for c in extraction.claims:
            cid = await db(
                repo.save_claim,
                analysis_id,
                text=c.text,
                claim_type=c.claim_type.value,
                importance=c.importance,
                time_sensitive=c.time_sensitive,
                requires_external_evidence=c.requires_external_evidence,
                verification_query=c.verification_query,
                source_quote=c.source_quote,
            )
            claim_ids.append(cid)
        if not extraction.claims:
            warnings.append("Nenhuma alegação factual verificável foi identificada no conteúdo.")

        # ------------------------------------------------ 4-6. search + evidence
        await step(AnalysisStatus.INVESTIGATING, "Buscando evidências")
        sem = asyncio.Semaphore(2)
        facts_by_claim: dict[int, list[EvidenceFact]] = {}
        verifiable = [
            (cid, c)
            for cid, c in zip(claim_ids, extraction.claims, strict=True)
            if c.claim_type not in NON_VERIFIABLE_TYPES
        ]
        llm_down = False
        for i, (cid, c) in enumerate(verifiable, start=1):
            facts_by_claim[cid] = []
            if llm_down:
                continue
            if i > 1:
                await asyncio.sleep(0.4)
            await db(
                repo.set_status,
                analysis_id,
                AnalysisStatus.INVESTIGATING,
                f"Buscando evidências ({i}/{len(verifiable)})",
            )
            await note(f"Buscando: {c.verification_query}")
            try:
                gathered = await gather_evidence(
                    claim_text=c.text,
                    query=c.verification_query,
                    provider=deps.provider,
                    fetcher=deps.fetcher,
                    gateway=deps.gateway,
                    depth=depth,
                    exclude_domain=doc.domain,
                    usage=usage,
                    warnings=warnings,
                    semaphore=sem,
                )
            except LLMUnavailable as exc:
                warnings.append(str(exc))
                llm_down = True
                continue
            except ReliabilityError as exc:
                warnings.append(f"Falha ao investigar uma alegação: {exc}")
                continue
            for g in gathered:
                sid = await db(
                    repo.get_or_create_source,
                    analysis_id,
                    url=g.source.url,
                    title=g.source.title,
                    publisher=g.source.publisher,
                    domain=g.source.domain,
                    published_at=g.source.published_at,
                    is_paywalled=g.source.is_paywalled,
                )
                await db(
                    repo.add_evidence,
                    cid,
                    sid,
                    stance=g.judgement.stance.value,
                    relevance=g.judgement.relevance,
                    exact_quote=g.judgement.exact_quote,
                    omits_context=g.judgement.omits_context,
                )
                facts_by_claim[cid].append(
                    EvidenceFact(
                        domain=g.source.domain or g.source.url,
                        stance=Stance(g.judgement.stance),
                        relevance=g.judgement.relevance,
                        omits_context=g.judgement.omits_context,
                    )
                )
            await note(f"{len(gathered)} evidência(s) válida(s) com trecho verificado")

        # ------------------------------------------------ 7-8. deterministic classification + tags
        await step(AnalysisStatus.CLASSIFYING, "Classificando (regras determinísticas)")
        outcomes: list[ClaimOutcome] = []
        for cid, c in zip(claim_ids, extraction.claims, strict=True):
            facts = ClaimFacts(
                claim_type=c.claim_type,
                importance=c.importance,
                time_sensitive=c.time_sensitive,
                evidences=tuple(facts_by_claim.get(cid, [])),
            )
            result = evaluate_claim(facts)
            await db(repo.set_claim_verdict, cid, result.verdict, result.rationale)
            outcomes.append(ClaimOutcome(cid, c.text, facts, result))

        doc_facts = DocFacts(
            input_type=input_type,
            url=doc.url,
            author=doc.author,
            publisher=doc.publisher,
            published_at=doc.published_at,
            document_text=text,
            emotional_quotes=tuple(extraction.emotional_quotes),
            assertive_opinion_quotes=tuple(extraction.assertive_opinion_quotes),
        )
        tags = assign_tags(
            doc_facts,
            outcomes,
            now=datetime.now(UTC).replace(tzinfo=None),
            outdated_after_days=deps.settings.outdated_after_days,
        )
        await db(
            repo.save_tags, analysis_id, [(t.code, t.justification, t.claim_id) for t in tags]
        )
        overall = classify_overall([o.result.verdict for o in outcomes], [t.code for t in tags])

        # ------------------------------------------------ 9. wrap-up + telemetry
        await flush_warnings()
        final = AnalysisStatus.PARTIAL if warnings else AnalysisStatus.COMPLETED
        await db(
            repo.finalize,
            analysis_id,
            status=final,
            overall_status=overall.status,
            overall_reason=overall.reason,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            processing_time_ms=elapsed_ms(),
        )
        await db(repo.add_event, analysis_id, final.value, f"Análise finalizada: {overall.status.value}")

    except asyncio.CancelledError:
        await flush_warnings()
        await db(
            repo.finalize,
            analysis_id,
            status=AnalysisStatus.CANCELLED,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            processing_time_ms=elapsed_ms(),
            error_message="Análise cancelada pelo usuário.",
        )
        await db(repo.add_event, analysis_id, "CANCELLED", "Análise cancelada pelo usuário.")
        raise
    except (ReliabilityError, InvalidInput) as exc:
        await fail(str(exc))
    except Exception as exc:
        log.exception("Unexpected pipeline failure")
        await fail(f"Erro inesperado durante a análise ({type(exc).__name__}). Veja o log.")
