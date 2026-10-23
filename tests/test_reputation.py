"""Tests for domain reputation catalog and fact-checking tiering."""

from __future__ import annotations

from reliability.search.reputation import (
    SourceTier,
    build_factcheck_queries,
    classify_url_tier,
    tier_badge_info,
    tier_weight,
)


def test_classify_tier_1_fact_checking():
    assert classify_url_tier("https://www.aosfatos.org/noticias/checagem-fato/") is SourceTier.TIER_1_FACT_CHECK
    assert classify_url_tier("https://lupa.news/relatorio/") is SourceTier.TIER_1_FACT_CHECK
    assert classify_url_tier("https://www.boatos.org/brasil/post.html") is SourceTier.TIER_1_FACT_CHECK
    assert classify_url_tier("https://g1.globo.com/fato-ou-fake/noticia/2026/01/fato.ghtml") is SourceTier.TIER_1_FACT_CHECK
    assert classify_url_tier("https://politica.estadao.com.br/blogs/estadao-verifica/desmentido/") is SourceTier.TIER_1_FACT_CHECK
    assert classify_url_tier("https://noticias.uol.com.br/confere/ultimas-noticias/2026/01/01/boato.htm") is SourceTier.TIER_1_FACT_CHECK
    assert classify_url_tier("https://projetocomprova.com.br/publicacoes/checagem") is SourceTier.TIER_1_FACT_CHECK
    assert classify_url_tier("https://www.snopes.com/fact-check/claim") is SourceTier.TIER_1_FACT_CHECK


def test_classify_tier_2_authority():
    assert classify_url_tier("https://g1.globo.com/economia/noticia/2026/01/pib.ghtml") is SourceTier.TIER_2_AUTHORITY
    assert classify_url_tier("https://www1.folha.uol.com.br/mercado/2026/01/inflacao.shtml") is SourceTier.TIER_2_AUTHORITY
    assert classify_url_tier("https://www.gov.br/fazenda/pt-br/assuntos/noticias") is SourceTier.TIER_2_AUTHORITY
    assert classify_url_tier("https://portal.stf.jus.br/noticias/detalhe.asp") is SourceTier.TIER_2_AUTHORITY
    assert classify_url_tier("https://www.bbc.com/portuguese/articles/c000") is SourceTier.TIER_2_AUTHORITY
    assert classify_url_tier("https://www.reuters.com/world/americas/economy-report-2026") is SourceTier.TIER_2_AUTHORITY


def test_classify_tier_3_general():
    assert classify_url_tier("https://meublogpessoal.wordpress.com/post") is SourceTier.TIER_3_GENERAL
    assert classify_url_tier("https://forumqualquer.net/discussao") is SourceTier.TIER_3_GENERAL
    assert classify_url_tier("") is SourceTier.TIER_3_GENERAL


def test_tier_weights_ordering():
    assert tier_weight(SourceTier.TIER_1_FACT_CHECK) > tier_weight(SourceTier.TIER_2_AUTHORITY)
    assert tier_weight(SourceTier.TIER_2_AUTHORITY) > tier_weight(SourceTier.TIER_3_GENERAL)


def test_build_factcheck_queries():
    queries = build_factcheck_queries("O governo decretou feriado bancário nacional de 10 dias")
    assert len(queries) >= 2
    assert any("fato ou fake" in q for q in queries)
    assert any("é verdade" in q for q in queries)


def test_tier_badge_info():
    badge, color, desc = tier_badge_info(SourceTier.TIER_1_FACT_CHECK)
    assert "Tier 1" in badge
    assert color.startswith("#")
    assert len(desc) > 10
