"""Deterministic tag assignment (RF-10). Every tag carries a code-generated justification."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from reliability.schemas import ClaimVerdict, TagCode, quote_in_text
from reliability.verification.rules import ClaimFacts, VerdictResult

SHORTENERS = {
    "bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly",
    "cutt.ly", "shorturl.at", "t.ly", "rb.gy", "tiny.cc", "lnkd.in", "wa.me", "bl.ink",
}
RISKY_TLDS = {"zip", "mov", "tk", "ml", "ga", "cf", "gq", "click", "country", "kim", "loan", "men"}
MIN_EMOTIONAL_QUOTES = 2


@dataclass(frozen=True)
class DocFacts:
    input_type: str  # "url" | "text"
    url: str | None = None
    author: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    document_text: str = ""
    emotional_quotes: tuple[str, ...] = ()
    assertive_opinion_quotes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagDecision:
    code: TagCode
    justification: str
    claim_id: int | None = None


@dataclass(frozen=True)
class ClaimOutcome:
    claim_id: int
    text: str
    facts: ClaimFacts
    result: VerdictResult


def suspicious_url_reasons(url: str) -> list[str]:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    reasons: list[str] = []
    if "@" in parts.netloc:
        reasons.append("contém '@' (credenciais/ofuscação de host)")
    try:
        ipaddress.ip_address(host.strip("[]"))
        reasons.append("usa endereço IP em vez de domínio")
    except ValueError:
        pass
    if host in SHORTENERS:
        reasons.append("é um encurtador de links (destino oculto)")
    if any(label.startswith("xn--") for label in host.split(".")):
        reasons.append("usa domínio punycode (possível imitação visual de outro domínio)")
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if tld in RISKY_TLDS:
        reasons.append(f"usa o TLD '.{tld}', frequentemente associado a abuso")
    return reasons


def _short(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def assign_tags(
    doc: DocFacts,
    outcomes: list[ClaimOutcome],
    *,
    now: datetime,
    outdated_after_days: int = 365,
) -> list[TagDecision]:
    tags: list[TagDecision] = []

    # ---- source / origin / link
    if doc.input_type == "text":
        tags.append(
            TagDecision(
                TagCode.ORIGEM_NAO_CONFIRMADA,
                "O conteúdo foi colado como texto, sem URL: autoria, veículo e data originais não "
                "puderam ser confirmados.",
            )
        )
    else:
        if not doc.author and not doc.publisher:
            tags.append(
                TagDecision(
                    TagCode.FONTE_NAO_IDENTIFICADA,
                    "A página não informa autor nem veículo/publicador identificável nos metadados.",
                )
            )
        if doc.url:
            reasons = suspicious_url_reasons(doc.url)
            if reasons:
                tags.append(
                    TagDecision(TagCode.LINK_SUSPEITO, "O link " + "; ".join(reasons) + ".")
                )

    # ---- communication (only with quotes verified literally in the document)
    emo = [q for q in doc.emotional_quotes if quote_in_text(q, doc.document_text)]
    if len(emo) >= MIN_EMOTIONAL_QUOTES:
        tags.append(
            TagDecision(
                TagCode.APELO_EMOCIONAL,
                f"{len(emo)} trechos com linguagem emocional marcada, ex.: “{_short(emo[0])}”.",
            )
        )
    opi = [q for q in doc.assertive_opinion_quotes if quote_in_text(q, doc.document_text)]
    if opi:
        tags.append(
            TagDecision(
                TagCode.OPINIAO_COMO_FATO,
                f"Opinião apresentada como fato, ex.: “{_short(opi[0])}”.",
            )
        )

    # ---- date
    time_sensitive = [o for o in outcomes if o.facts.time_sensitive]
    if doc.published_at and time_sensitive:
        age_days = (now - doc.published_at).days
        if age_days > outdated_after_days:
            tags.append(
                TagDecision(
                    TagCode.DATA_DESATUALIZADA,
                    f"O conteúdo foi publicado há ~{age_days} dias (limite: {outdated_after_days}) "
                    f"e contém alegação sensível ao tempo: “{_short(time_sensitive[0].text)}”.",
                )
            )

    # ---- per-claim
    for o in outcomes:
        r = o.result
        label = f"“{_short(o.text)}”"
        if r.verdict is ClaimVerdict.NOT_VERIFIABLE:
            continue
        if r.contradicts >= 1:
            tags.append(
                TagDecision(
                    TagCode.CONTRADICAO_ENCONTRADA,
                    f"{r.contradicts} fonte(s) contradizem {label}.",
                    o.claim_id,
                )
            )
        if r.rule_id == 2 and o.facts.importance >= 2:
            tags.append(
                TagDecision(
                    TagCode.EVIDENCIA_INSUFICIENTE,
                    f"Nenhuma evidência válida encontrada para a alegação relevante {label}.",
                    o.claim_id,
                )
            )
        if r.verdict is ClaimVerdict.CORROBORATED and r.supports + r.partial == 1:
            tags.append(
                TagDecision(
                    TagCode.FONTES_INDEPENDENTES_INSUFICIENTES,
                    f"{label} é sustentada por apenas 1 fonte independente.",
                    o.claim_id,
                )
            )
        if r.omits_context:
            tags.append(
                TagDecision(
                    TagCode.FORA_DE_CONTEXTO,
                    f"Fonte(s) indicam que {label} omite contexto relevante.",
                    o.claim_id,
                )
            )
    return tags
