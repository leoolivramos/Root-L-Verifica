"""Forensic methodological confidence calculation (RNF-03 compliant: no LLM)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from reliability.schemas import ClaimVerdict, Stance


@dataclass(frozen=True)
class ConfidenceEvidence:
    domain: str
    stance: Stance
    relevance: float
    tier: str = "tier_3_general"


@dataclass(frozen=True)
class ConfidenceClaim:
    verdict: ClaimVerdict
    importance: int
    evidences: Sequence[ConfidenceEvidence]


@dataclass(frozen=True)
class ForensicConfidenceResult:
    score: float  # 0.0 to 1.0
    percentage: int  # 0 to 100
    level: str  # "Alta", "Média", "Baixa"
    label: str  # Full descriptive label
    explanation: str
    tier1_count: int
    tier2_count: int
    tier3_count: int
    total_sources: int


def calculate_forensic_confidence(
    claims: Sequence[ConfidenceClaim],
) -> ForensicConfidenceResult:
    """Deterministically compute the methodological certainty level of the verification.

    Factors:
    1. Independent source breadth (distinct domains).
    2. Quality tier mix (Tier 1 Fact-Check vs Tier 2 Authority vs Tier 3 General).
    3. Stance consistency / absence of contradictory evidence.
    4. Resolution rate of claims (verifiable vs inconclusive).
    """
    if not claims:
        return ForensicConfidenceResult(
            score=0.20,
            percentage=20,
            level="Baixa",
            label="Baixa Certeza Metodológica (20%)",
            explanation="Nenhuma alegação factual foi avaliada com evidências.",
            tier1_count=0,
            tier2_count=0,
            tier3_count=0,
            total_sources=0,
        )

    all_evidences = [ev for c in claims for ev in c.evidences]
    unique_domains = {ev.domain for ev in all_evidences if ev.domain}

    t1_count = len({ev.domain for ev in all_evidences if "tier_1" in ev.tier})
    t2_count = len({ev.domain for ev in all_evidences if "tier_2" in ev.tier})
    t3_count = len({ev.domain for ev in all_evidences if "tier_3" in ev.tier})

    # 1. Source breadth score (0.0 to 1.0)
    # 1 source = 0.45, 2 sources = 0.70, 3+ sources = 1.0
    n_domains = len(unique_domains)
    if n_domains == 0:
        breadth_score = 0.15
    elif n_domains == 1:
        breadth_score = 0.45
    elif n_domains == 2:
        breadth_score = 0.75
    else:
        breadth_score = 1.0

    # 2. Quality tier score (0.0 to 1.0)
    # Presence of Tier 1 (IFCN fact-check) provides maximum authority boost
    if t1_count >= 1:
        quality_score = 1.0
    elif t2_count >= 2:
        quality_score = 0.90
    elif t2_count == 1:
        quality_score = 0.75
    elif t3_count > 0:
        quality_score = 0.50
    else:
        quality_score = 0.20

    # 3. Claim resolution rate
    conclusive_claims = [
        c
        for c in claims
        if c.verdict in (ClaimVerdict.CORROBORATED, ClaimVerdict.CONTRADICTED, ClaimVerdict.PARTIALLY_CORROBORATED)
    ]
    resolution_rate = len(conclusive_claims) / max(1, len(claims))

    # 4. Consistency factor
    # Contradicting evidences within the same claim reduce consensus slightly if unresolved
    has_mixed_signals = False
    for c in claims:
        stances = {ev.stance for ev in c.evidences}
        if Stance.SUPPORTS in stances and Stance.CONTRADICTS in stances:
            has_mixed_signals = True
            break
    consistency_factor = 0.85 if has_mixed_signals else 1.0

    # Composite weighted score
    raw_score = (
        breadth_score * 0.35 + quality_score * 0.40 + resolution_rate * 0.25
    ) * consistency_factor

    # Cap between 0.10 and 1.0
    score = max(0.10, min(1.0, round(raw_score, 2)))
    pct = int(round(score * 100))

    if score >= 0.80:
        level = "Alta"
        label = f"Alta Certeza Metodológica ({pct}%)"
        explanation = (
            f"Forte lastro probatório ({n_domains} domínio(s) independente(s), "
            f"com presença de agências de checagem/veículos de referência e alta consistência)."
        )
    elif score >= 0.55:
        level = "Média"
        label = f"Média Certeza Metodológica ({pct}%)"
        explanation = (
            f"Lastro probatório moderado ({n_domains} domínio(s) avaliado(s)). "
            "Recomenda-se leitura crítica das fontes citadas."
        )
    else:
        level = "Baixa"
        label = f"Baixa Certeza Metodológica ({pct}%)"
        explanation = (
            "Poucas fontes independentes ou evidências inconclusivas encontradas na busca pública."
        )

    return ForensicConfidenceResult(
        score=score,
        percentage=pct,
        level=level,
        label=label,
        explanation=explanation,
        tier1_count=t1_count,
        tier2_count=t2_count,
        tier3_count=t3_count,
        total_sources=n_domains,
    )
