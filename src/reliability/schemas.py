"""Pydantic contracts: LLM structured outputs, enums and report models."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator


# --------------------------------------------------------------------------- enums
class AnalysisStatus(StrEnum):
    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    INVESTIGATING = "INVESTIGATING"
    CLASSIFYING = "CLASSIFYING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = {
    AnalysisStatus.COMPLETED,
    AnalysisStatus.PARTIAL,
    AnalysisStatus.FAILED,
    AnalysisStatus.CANCELLED,
}


class Depth(StrEnum):
    FAST = "rapida"
    DEEP = "profunda"


class ClaimType(StrEnum):
    QUANTITATIVE_FACT = "quantitative_fact"
    EVENT = "event"
    ATTRIBUTION = "attribution"
    SCIENTIFIC = "scientific"
    OPINION = "opinion"
    PREDICTION = "prediction"
    SUBJECTIVE = "subjective"
    OTHER_FACT = "other_fact"


NON_VERIFIABLE_TYPES = {ClaimType.OPINION, ClaimType.PREDICTION, ClaimType.SUBJECTIVE}


class Stance(StrEnum):
    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


class ClaimVerdict(StrEnum):
    CORROBORATED = "corroborada"
    CONTRADICTED = "contradita"
    PARTIALLY_CORROBORATED = "parcialmente_corroborada"
    INCONCLUSIVE = "inconclusiva"
    NOT_VERIFIABLE = "nao_verificavel"


VERDICT_LABELS = {
    ClaimVerdict.CORROBORATED: "Corroborada",
    ClaimVerdict.CONTRADICTED: "Contradita",
    ClaimVerdict.PARTIALLY_CORROBORATED: "Parcialmente corroborada",
    ClaimVerdict.INCONCLUSIVE: "Inconclusiva",
    ClaimVerdict.NOT_VERIFIABLE: "Não verificável",
}


class OverallStatus(StrEnum):
    WELL_CORROBORATED = "Muito bem corroborado"
    CORROBORATED_WITH_CAVEATS = "Corroborado com ressalvas"
    MIXED = "Conteúdo misto"
    INSUFFICIENT = "Evidências insuficientes"
    CONTRADICTED = "Contém alegações contraditas"


class TagCode(StrEnum):
    FONTE_NAO_IDENTIFICADA = "fonte_nao_identificada"
    FONTES_INDEPENDENTES_INSUFICIENTES = "fontes_independentes_insuficientes"
    EVIDENCIA_INSUFICIENTE = "evidencia_insuficiente"
    CONTRADICAO_ENCONTRADA = "contradicao_encontrada"
    FORA_DE_CONTEXTO = "fora_de_contexto"
    DATA_DESATUALIZADA = "data_desatualizada"
    APELO_EMOCIONAL = "apelo_emocional"
    OPINIAO_COMO_FATO = "opiniao_como_fato"
    ORIGEM_NAO_CONFIRMADA = "origem_nao_confirmada"
    LINK_SUSPEITO = "link_suspeito"


TAG_LABELS = {
    TagCode.FONTE_NAO_IDENTIFICADA: "Fonte não identificada",
    TagCode.FONTES_INDEPENDENTES_INSUFICIENTES: "Fontes independentes insuficientes",
    TagCode.EVIDENCIA_INSUFICIENTE: "Evidência insuficiente",
    TagCode.CONTRADICAO_ENCONTRADA: "Contradição encontrada",
    TagCode.FORA_DE_CONTEXTO: "Fora de contexto",
    TagCode.DATA_DESATUALIZADA: "Data desatualizada",
    TagCode.APELO_EMOCIONAL: "Apelo emocional",
    TagCode.OPINIAO_COMO_FATO: "Opinião como fato",
    TagCode.ORIGEM_NAO_CONFIRMADA: "Origem não confirmada",
    TagCode.LINK_SUSPEITO: "Link suspeito",
}

# Tags that downgrade an otherwise fully corroborated content to "com ressalvas".
CAVEAT_TAGS = {
    TagCode.FONTES_INDEPENDENTES_INSUFICIENTES,
    TagCode.FORA_DE_CONTEXTO,
    TagCode.DATA_DESATUALIZADA,
    TagCode.LINK_SUSPEITO,
}


# ------------------------------------------------------------- quote verification
_QUOTE_TRANS = str.maketrans(
    {"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "–": "-", "—": "-", " ": " "}
)


def normalize_for_match(text: str) -> str:
    """Normalise text for literal-quote matching (case, whitespace, quotes, accents kept)."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_TRANS)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def quote_in_text(quote: str, text: str) -> bool:
    """True iff `quote` appears literally (after normalisation) inside `text`."""
    q = normalize_for_match(quote)
    if not q:
        return False
    n_text = normalize_for_match(text)
    if q in n_text:
        return True
    # Also check without leading/trailing quotes (models often wrap quotes in quotation marks)
    q_stripped = q.strip('"\' ')
    return bool(q_stripped) and q_stripped in n_text


def _check_quote(quote: str, info: ValidationInfo, key: str = "source_text") -> str:
    ctx = info.context or {}
    source = ctx.get(key)
    if source is not None and not quote_in_text(quote, source):
        raise ValueError(
            f"O trecho {quote!r} NÃO aparece literalmente no documento. "
            "Copie o trecho exatamente como está escrito, sem parafrasear."
        )
    return quote


# ------------------------------------------------------------ LLM contracts (step 3)
class ExtractedClaim(BaseModel):
    text: str = Field(..., min_length=5, description="O texto exato da alegação")
    claim_type: ClaimType = Field(..., description="Tipo da alegação")
    verification_query: str = Field(
        ..., min_length=3, description="String de busca otimizada para DuckDuckGo"
    )
    requires_external_evidence: bool
    importance: Literal[1, 2, 3] = Field(2, description="1=baixa, 3=central para o conteúdo")
    time_sensitive: bool = Field(False, description="A veracidade depende da data atual")
    source_quote: str = Field(..., description="Trecho literal do documento que contém a alegação")

    @field_validator("source_quote")
    @classmethod
    def _quote_exists(cls, v: str, info: ValidationInfo) -> str:
        return _check_quote(v, info)


class ExtractionResult(BaseModel):
    summary: str = Field(
        "", description="Resumo objetivo (2-3 frases) do que o documento afirma, sem opinião"
    )
    claims: list[ExtractedClaim]
    emotional_quotes: list[str] = Field(
        default_factory=list,
        description="Trechos literais com linguagem emocionalmente manipulativa",
    )
    assertive_opinion_quotes: list[str] = Field(
        default_factory=list,
        description="Trechos literais em que uma opinião é apresentada como fato",
    )

    @field_validator("emotional_quotes", "assertive_opinion_quotes")
    @classmethod
    def _quotes_exist(cls, v: list[str], info: ValidationInfo) -> list[str]:
        return [_check_quote(q, info) for q in v]


# ------------------------------------------------------------ LLM contracts (step 6)
class EvidenceJudgement(BaseModel):
    stance: Stance
    relevance: float = Field(..., ge=0, le=1, description="0 a 1: quão diretamente trata da alegação")
    exact_quote: str = Field(..., description="Trecho literal da fonte que fundamenta o julgamento")
    omits_context: bool = Field(
        False, description="A fonte mostra que a alegação omite contexto relevante"
    )

    @field_validator("exact_quote")
    @classmethod
    def _quote_exists(cls, v: str, info: ValidationInfo) -> str:
        return _check_quote(v, info)


# ------------------------------------------------------------------- report models
class EvidenceView(BaseModel):
    source_url: str
    source_title: str | None = None
    publisher: str | None = None
    domain: str | None = None
    published_at: datetime | None = None
    is_paywalled: bool = False
    stance: Stance
    relevance: float
    exact_quote: str
    omits_context: bool = False


class TagView(BaseModel):
    code: TagCode
    justification: str
    claim_id: int | None = None


class ClaimReport(BaseModel):
    id: int
    text: str
    claim_type: ClaimType
    importance: int
    verification_status: ClaimVerdict
    rationale: str | None = None
    evidences: list[EvidenceView] = Field(default_factory=list)
    tags: list[TagView] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    id: int
    input_type: Literal["url", "text"]
    original_input: str
    title: str | None = None
    domain: str | None = None
    status: AnalysisStatus
    overall_status: OverallStatus | None = None
    overall_reason: str | None = None
    depth: Depth = Depth.FAST
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None
    tags: list[TagView] = Field(default_factory=list)  # analysis-level tags
    claims: list[ClaimReport] = Field(default_factory=list)
    pipeline_version: str = ""
    prompt_version: str = ""
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    processing_time_ms: int = 0
    created_at: datetime | None = None
    feedback_given: bool = False
    media_type: str | None = None
    media_url: str | None = None
