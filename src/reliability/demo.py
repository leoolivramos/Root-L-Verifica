"""Deterministic fakes: scripted LLM, fake search and fake fetcher.

Used by the test-suite and by the `RELIABILITY_DEMO=1` mode of the UI (no network, no model).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Sequence
from datetime import datetime

from pydantic import BaseModel, ValidationError

from reliability.claims.llm import Usage
from reliability.errors import StructuredOutputError
from reliability.extraction.fetcher import FetchResult
from reliability.schemas import (
    EvidenceJudgement,
    ExtractionResult,
)
from reliability.search.base import SearchHit

Attempts = Sequence[dict | str]
Handler = Callable[[type[BaseModel], str, str, str], Attempts]


class FakeLLMGateway:
    """Mimics instructor: tries each scripted raw output in order (as retries), validating
    with the same Pydantic models + context, and raises StructuredOutputError when none is valid."""

    def __init__(self, handler: Handler | None = None, *, max_retries: int = 3, delay_s: float = 0.0):
        self.handler = handler or default_demo_handler
        self.max_retries = max_retries
        self.delay_s = delay_s
        self.calls: list[dict] = []  # recorded requests (system/user/attempts) for assertions

    async def structured(self, response_model, *, system: str, user: str, source_text: str):
        usage = Usage()
        attempts = list(self.handler(response_model, system, user, source_text))[: self.max_retries]
        self.calls.append(
            {"model": response_model, "system": system, "user": user, "n_attempts": len(attempts)}
        )
        for raw in attempts:
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            usage.prompt_tokens += (len(system) + len(user)) // 4
            usage.completion_tokens += max(1, len(raw if isinstance(raw, str) else json.dumps(raw)) // 4)
            try:
                ctx = {"source_text": source_text}
                if isinstance(raw, str):
                    return response_model.model_validate_json(raw, context=ctx), usage
                return response_model.model_validate(raw, context=ctx), usage
            except (ValidationError, ValueError):
                continue
        raise StructuredOutputError(
            f"O modelo não retornou uma resposta estruturada válida após {self.max_retries} tentativas.",
            usage.prompt_tokens,
            usage.completion_tokens,
        )

    async def analyze_image(
        self, image_bytes: bytes, mime_type: str = "image/jpeg", prompt: str = ""
    ) -> tuple[str, Usage]:
        return (
            "Texto visível na imagem (OCR): Notícia oficial informando dados e estatísticas.\n\n"
            "Descrição visual da foto: Fotografia em alta resolução retratando o evento e pessoas presentes.\n\n"
            "Alegações factuais: O evento ocorreu conforme registrado e as informações foram confirmadas.",
            Usage(prompt_tokens=150, completion_tokens=80),
        )

    async def analyze_frames(
        self, frames: list[bytes], prompt: str = ""
    ) -> tuple[str, Usage]:
        return (
            "Texto na tela (OCR): Títulos e legendas do vídeo.\n\n"
            "Descrição da ação: Sequência de eventos gravada em vídeo mostrando os fatos narrados.\n\n"
            "Alegações factuais: O vídeo demonstra as ações e fatos descritos pelo conteúdo.",
            Usage(prompt_tokens=250, completion_tokens=120),
        )


# ------------------------------------------------------------------ demo behaviours
_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_OPINION_RE = re.compile(r"\b(acho|melhor|pior|deveria|na minha opinião|incrível|absurdo)\b", re.IGNORECASE)
_PREDICT_RE = re.compile(r"\b(vai acontecer|será|no futuro|em breve|nos próximos)\b", re.IGNORECASE)


def default_demo_handler(model: type[BaseModel], system: str, user: str, source_text: str) -> Attempts:
    if model is ExtractionResult:
        sentences = [s.strip() for s in _SENT_RE.split(source_text.replace("\n", " ")) if len(s.strip()) > 25]
        claims = []
        for s in sentences:
            if _OPINION_RE.search(s):
                ctype, req = "opinion", False
            elif _PREDICT_RE.search(s):
                ctype, req = "prediction", False
            elif re.search(r"\d", s):
                ctype, req = "quantitative_fact", True
            else:
                ctype, req = "other_fact", True
            words = re.findall(r"\w{4,}", s)
            claims.append(
                {
                    "text": s,
                    "claim_type": ctype,
                    "verification_query": " ".join(words[:8]) or s[:40],
                    "requires_external_evidence": req,
                    "importance": 3 if re.search(r"\d", s) else 2,
                    "time_sensitive": bool(re.search(r"\b20\d\d\b", s)),
                    "source_quote": s,
                }
            )
        emo = [s for s in sentences if s.count("!") >= 1][:3]
        opi = [s for s in sentences if _OPINION_RE.search(s)][:1]
        return [
            {
                "summary": "Resumo (modo demonstração): " + " ".join(sentences[:2])[:240],
                "claims": claims[:10],
                "emotional_quotes": emo,
                "assertive_opinion_quotes": opi,
            }
        ]
    if model is EvidenceJudgement:
        low = source_text.lower()
        sentences = [s.strip() for s in _SENT_RE.split(source_text.replace("\n", " ")) if s.strip()]
        quote = sentences[0] if sentences else source_text[:120]
        if "desmente" in low or "falso" in low:
            stance, rel = "contradicts", 0.9
        elif "em parte" in low or "parcialmente" in low:
            stance, rel = "partially_supports", 0.7
        elif "confirma" in low:
            stance, rel = "supports", 0.85
        else:
            stance, rel = "neutral", 0.1
        return [
            {
                "stance": stance,
                "relevance": rel,
                "exact_quote": quote,
                "omits_context": "sem contexto" in low,
            }
        ]
    return []


class FakeSearchProvider:
    """Deterministic search: the scenario is derived from a hash of the query."""

    name = "fake"

    def __init__(self, scenarios: dict[str, list[SearchHit]] | None = None):
        self.scenarios = scenarios or {}
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        self.queries.append(query)
        if query in self.scenarios:
            return self.scenarios[query][:max_results]
        h = int(hashlib.sha256(query.encode()).hexdigest(), 16) % 5
        topic = query[:80]
        page_id = int(hashlib.md5(query.encode()).hexdigest(), 16) % 9999

        def mk(i: int, body: str) -> SearchHit:
            return SearchHit(
                url=f"https://fonte{i}{h}.com.br/materia/{page_id}",
                title=f"Cobertura {i}: {topic}",
                snippet=body,
                published_at=datetime(2026, 1, 10),
            )
        if h == 0:  # strongly corroborated
            return [
                mk(1, f"A agência confirma os dados sobre {topic}. Levantamento oficial publicado."),
                mk(2, f"Segundo relatório independente, o órgão confirma {topic}."),
                mk(3, f"Reportagem confirma o ocorrido: {topic}."),
            ][:max_results]
        if h == 1:  # contradicted
            return [
                mk(1, f"Checagem desmente a afirmação sobre {topic}. A informação é falsa."),
                mk(2, f"Especialistas desmentem: {topic} não procede."),
            ][:max_results]
        if h == 2:  # partial
            return [mk(1, f"Os dados sobre {topic} procedem em parte, com ressalvas importantes.")][:max_results]
        if h == 3:  # conflicting
            return [
                mk(1, f"Um estudo confirma {topic}."),
                mk(2, f"Outra análise desmente {topic}."),
            ][:max_results]
        return []  # no evidence


_DEMO_HTML = """<html><head><title>Notícia de demonstração</title></head><body><article>
<h1>Notícia de demonstração</h1>
<p>O governo anunciou em 2026 que a inflação anual ficou em 4,2% no último trimestre. Os dados foram divulgados por um instituto.</p>
<p>O desempenho da economia foi um absurdo e uma tragédia para todos! Isso é uma vergonha sem tamanho!</p>
<p>A população de 12 milhões de habitantes cresceu 3% desde 2020, segundo o texto, e novas obras serão entregues em breve.</p>
</article></body></html>"""


class DemoFetcher:
    """Returns canned HTML for any URL (never touches the network)."""

    async def fetch(self, url: str) -> FetchResult:
        await asyncio.sleep(0.2)
        return FetchResult(url=url, status_code=200, content_type="text/html", text=_DEMO_HTML)
