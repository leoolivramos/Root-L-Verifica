"""Deterministic per-claim verdict rules (RNF-03). NO LLM code may be imported here."""

from __future__ import annotations

from dataclasses import dataclass, field

from reliability.schemas import NON_VERIFIABLE_TYPES, ClaimType, ClaimVerdict, Stance

MIN_RELEVANCE = 0.5


@dataclass(frozen=True)
class EvidenceFact:
    domain: str
    stance: Stance
    relevance: float
    omits_context: bool = False
    quote_verified: bool = True


@dataclass(frozen=True)
class ClaimFacts:
    claim_type: ClaimType
    importance: int = 2
    time_sensitive: bool = False
    evidences: tuple[EvidenceFact, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VerdictResult:
    verdict: ClaimVerdict
    rule_id: int
    rationale: str
    supports: int = 0
    partial: int = 0
    contradicts: int = 0
    valid_evidence: int = 0
    omits_context: bool = False


def valid_evidence(facts: ClaimFacts) -> list[EvidenceFact]:
    """Evidence usable by the rules: verified quote, relevant, one per independent domain
    (the most relevant one when a domain appears several times)."""
    best: dict[str, EvidenceFact] = {}
    for e in facts.evidences:
        if not e.quote_verified or e.relevance < MIN_RELEVANCE or e.stance is Stance.NEUTRAL:
            continue
        cur = best.get(e.domain)
        if cur is None or e.relevance > cur.relevance:
            best[e.domain] = e
    return list(best.values())


def evaluate_claim(facts: ClaimFacts) -> VerdictResult:
    """First matching rule wins (see README for the table)."""
    if facts.claim_type in NON_VERIFIABLE_TYPES:
        return VerdictResult(
            ClaimVerdict.NOT_VERIFIABLE,
            1,
            f"Regra 1: alegação do tipo '{facts.claim_type.value}' (opinião/previsão/juízo de valor) "
            "não é verificável factualmente.",
        )

    ev = valid_evidence(facts)
    s = sum(e.stance is Stance.SUPPORTS for e in ev)
    p = sum(e.stance is Stance.PARTIALLY_SUPPORTS for e in ev)
    c = sum(e.stance is Stance.CONTRADICTS for e in ev)
    ctx = any(e.omits_context for e in ev)
    counts = dict(supports=s, partial=p, contradicts=c, valid_evidence=len(ev), omits_context=ctx)

    if not ev:
        return VerdictResult(
            ClaimVerdict.INCONCLUSIVE,
            2,
            "Regra 2: nenhuma evidência válida (trecho verificado e relevante) foi encontrada.",
            **counts,
        )
    if c >= 1 and s + p == 0:
        return VerdictResult(
            ClaimVerdict.CONTRADICTED,
            3,
            f"Regra 3: {c} fonte(s) independente(s) contradizem a alegação e nenhuma a sustenta.",
            **counts,
        )
    if c >= 1 and s + p >= 1:
        # Dominância probatória: quando 2 ou mais fontes independentes desmentem e superam menções parciais isoladas
        if c >= 2 and c > (s + p):
            return VerdictResult(
                ClaimVerdict.CONTRADICTED,
                3,
                f"Regra 3: predomínio categórico de {c} fonte(s) independente(s) contradizendo a alegação, "
                f"superando menção parcial minoritária ({s + p} fonte).",
                **counts,
            )
        return VerdictResult(
            ClaimVerdict.INCONCLUSIVE,
            4,
            f"Regra 4: evidências conflitantes ({s + p} a favor/parcial, {c} contra); "
            "a divergência foi preservada sem média.",
            **counts,
        )
    if p >= 1:
        # Maioria qualificada: se 2 ou mais fontes sustentam integralmente e superam amplamente apoios parciais
        if s >= 2 and s > 2 * p:
            return VerdictResult(
                ClaimVerdict.CORROBORATED,
                6,
                f"Regra 6: {s} fontes sustentam a alegação integralmente, com ressalva minoritária de {p} fonte(s) parcial(is).",
                **counts,
            )
        return VerdictResult(
            ClaimVerdict.PARTIALLY_CORROBORATED,
            5,
            f"Regra 5: {p} fonte(s) sustentam apenas parte da alegação ({s} sustentam integralmente), "
            "sem contradições.",
            **counts,
        )
    return VerdictResult(
        ClaimVerdict.CORROBORATED,
        6,
        f"Regra 6: {s} fonte(s) independente(s) sustentam a alegação, sem contradições.",
        **counts,
    )
