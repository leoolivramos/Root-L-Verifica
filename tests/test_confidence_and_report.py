"""Tests for forensic confidence score and HTML dossier generator."""

from __future__ import annotations

from reliability.report.dossier import generate_forensic_html_report
from reliability.schemas import (
    AnalysisReport,
    AnalysisStatus,
    ClaimReport,
    ClaimType,
    ClaimVerdict,
    EvidenceView,
    OverallStatus,
    Stance,
)
from reliability.verification.confidence import (
    ConfidenceClaim,
    ConfidenceEvidence,
    calculate_forensic_confidence,
)


def test_calculate_forensic_confidence_high():
    claims = [
        ConfidenceClaim(
            verdict=ClaimVerdict.CORROBORATED,
            importance=3,
            evidences=[
                ConfidenceEvidence(domain="aosfatos.org", stance=Stance.SUPPORTS, relevance=0.95, tier="tier_1_fact_check"),
                ConfidenceEvidence(domain="g1.globo.com", stance=Stance.SUPPORTS, relevance=0.90, tier="tier_2_authority"),
                ConfidenceEvidence(domain="estadao.com.br", stance=Stance.SUPPORTS, relevance=0.88, tier="tier_2_authority"),
            ],
        )
    ]
    res = calculate_forensic_confidence(claims)
    assert res.score >= 0.80
    assert res.level == "Alta"
    assert res.tier1_count == 1
    assert res.tier2_count == 2
    assert res.total_sources == 3


def test_calculate_forensic_confidence_low():
    claims = [
        ConfidenceClaim(
            verdict=ClaimVerdict.INCONCLUSIVE,
            importance=2,
            evidences=[
                ConfidenceEvidence(domain="blog.com", stance=Stance.NEUTRAL, relevance=0.2, tier="tier_3_general"),
            ],
        )
    ]
    res = calculate_forensic_confidence(claims)
    assert res.score <= 0.60
    assert res.level == "Baixa"


def test_generate_forensic_html_report():
    rep = AnalysisReport(
        id=42,
        input_type="text",
        original_input="O PIB do Brasil cresceu 2,9% em 2025.",
        status=AnalysisStatus.COMPLETED,
        overall_status=OverallStatus.WELL_CORROBORATED,
        overall_reason="Confirmado por fontes oficiais do IBGE.",
        forensic_confidence=0.92,
        forensic_confidence_label="Alta Certeza Metodológica (92%)",
        claims=[
            ClaimReport(
                id=1,
                text="O PIB do Brasil cresceu 2,9% em 2025.",
                claim_type=ClaimType.QUANTITATIVE_FACT,
                importance=3,
                verification_status=ClaimVerdict.CORROBORATED,
                rationale="Regra 6: corroborada.",
                evidences=[
                    EvidenceView(
                        source_url="https://g1.globo.com/economia/pib.ghtml",
                        source_title="PIB cresce 2,9%",
                        publisher="G1",
                        domain="g1.globo.com",
                        stance=Stance.SUPPORTS,
                        relevance=0.95,
                        exact_quote="O PIB do Brasil fechou 2025 em alta de 2,9%.",
                        tier="tier_2_authority",
                        tier_label="📰 Tier 2: Jornalismo / Oficial",
                    )
                ],
            )
        ],
        forensic_media_analysis={
            "format": "JPEG",
            "media_type": "image",
            "size_formatted": "1.2 MB",
            "size_bytes": 1258291,
            "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "md5": "0123456789abcdef0123456789abcdef",
            "dimensions": {"width": 1920, "height": 1080, "megapixels": 2.07},
            "is_edited": False,
            "software_detected": None,
            "alerts": [],
        },
    )

    html_out = generate_forensic_html_report(rep)
    assert "<!DOCTYPE html>" in html_out
    assert "LTP-000042" in html_out
    assert "Laudo Técnico Pericial de Confiabilidade" in html_out
    assert "Alta Certeza Metodológica (92%)" in html_out
    assert "O PIB do Brasil cresceu 2,9% em 2025." in html_out
    assert "g1.globo.com" in html_out
    assert "Perícia Técnica de Mídia / Arquivo Digital" in html_out
    assert "abcdef1234567890" in html_out
