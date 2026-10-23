"""Domain reputation catalog and fact-checking tiering (RF-04 / RF-11)."""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlsplit

import tldextract

_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


class SourceTier(StrEnum):
    TIER_1_FACT_CHECK = "tier_1_fact_check"  # IFCN signatories & dedicated fact-check desks
    TIER_2_AUTHORITY = "tier_2_authority"  # Reference journalism, official government/legal
    TIER_3_GENERAL = "tier_3_general"  # General web, blogs, forums, aggregators


# IFCN signatories and dedicated fact-checking organizations
FACT_CHECK_DOMAINS = {
    "aosfatos.org",
    "lupa.news",
    "boatos.org",
    "e-farsas.com",
    "projetocomprova.com.br",
    "checamos.afp.com",
    "snopes.com",
    "politifact.com",
    "factcheck.org",
    "fullfact.org",
}

# Subpaths or specific sections of major portals dedicated to fact-checking
FACT_CHECK_URL_PATTERNS = [
    re.compile(r"fato-ou-fake", re.IGNORECASE),
    re.compile(r"estadao-verifica", re.IGNORECASE),
    re.compile(r"uol\.com\.br/.*(?:confere|comprova)", re.IGNORECASE),
    re.compile(r"reuters\.com/fact-check", re.IGNORECASE),
    re.compile(r"apnews\.com/.*fact-check", re.IGNORECASE),
    re.compile(r"afp\.com/.*fact-check", re.IGNORECASE),
    re.compile(r"checamos\.afp\.com", re.IGNORECASE),
]

# Tier 2: Reference media outlets and major news agencies
AUTHORITY_MEDIA_DOMAINS = {
    "g1.globo.com",
    "globo.com",
    "oglobo.globo.com",
    "valor.globo.com",
    "folha.uol.com.br",
    "folha.com.br",
    "estadao.com.br",
    "uol.com.br",
    "ebc.com.br",
    "agenciabrasil.ebc.com.br",
    "bbc.com",
    "bbc.co.uk",
    "reuters.com",
    "apnews.com",
    "afp.com",
    "dw.com",
    "elpais.com",
    "cnnbrasil.com.br",
    "cnn.com",
    "metropoles.com",
    "poder360.com.br",
    "nexojornal.com.br",
    "cartacapital.com.br",
    "r7.com",
    "terra.com.br",
    "theguardian.com",
    "nytimes.com",
    "wsj.com",
    "bloomberg.com",
}

AUTHORITY_SUFFIXES = (
    ".gov.br",
    ".jus.br",
    ".leg.br",
    ".mil.br",
    ".edu.br",
    ".org.br",
    ".gov",
    ".edu",
)


def classify_url_tier(url: str) -> SourceTier:
    """Classify a URL or domain into Tier 1 (Fact-Checking), Tier 2 (Authority), or Tier 3 (General)."""
    if not url:
        return SourceTier.TIER_3_GENERAL

    clean_url = url.strip().lower()

    # 1. Check specific fact-checking subpaths
    for pattern in FACT_CHECK_URL_PATTERNS:
        if pattern.search(clean_url):
            return SourceTier.TIER_1_FACT_CHECK

    host = urlsplit(clean_url).hostname or clean_url
    # Strip port if present
    if ":" in host:
        host = host.split(":")[0]

    ext = _TLD(host)
    domain = ext.top_domain_under_public_suffix or host

    # 2. Check dedicated fact-checking domains
    if domain in FACT_CHECK_DOMAINS or host in FACT_CHECK_DOMAINS:
        return SourceTier.TIER_1_FACT_CHECK

    # 3. Check official public institutional suffixes
    if any(host.endswith(sfx) for sfx in AUTHORITY_SUFFIXES):
        return SourceTier.TIER_2_AUTHORITY

    # 4. Check authoritative media domains
    if domain in AUTHORITY_MEDIA_DOMAINS or host in AUTHORITY_MEDIA_DOMAINS:
        return SourceTier.TIER_2_AUTHORITY

    return SourceTier.TIER_3_GENERAL


def tier_badge_info(tier: SourceTier) -> tuple[str, str, str]:
    """Returns (badge_icon_and_text, css_color, description)."""
    if tier is SourceTier.TIER_1_FACT_CHECK:
        return (
            "🛡️ Tier 1: Agência de Checagem",
            "#10b981",
            "Signatária da IFCN ou seção de fact-checking profissional especializada.",
        )
    if tier is SourceTier.TIER_2_AUTHORITY:
        return (
            "📰 Tier 2: Jornalismo / Oficial",
            "#3b82f6",
            "Veículo jornalístico consolidado, agência de notícias ou portal governamental/acadêmico.",
        )
    return (
        "🌐 Tier 3: Web Geral",
        "#6b7280",
        "Fonte pública geral da internet (blogs, portais independentes ou agregadores).",
    )


def tier_weight(tier: SourceTier) -> int:
    """Numerical weight for sorting and ranking candidates."""
    if tier is SourceTier.TIER_1_FACT_CHECK:
        return 30
    if tier is SourceTier.TIER_2_AUTHORITY:
        return 20
    return 10


def build_factcheck_queries(claim_text: str) -> list[str]:
    """Generate targeted queries to surface debunks and fact-checking investigations."""
    clean = re.sub(r'["“”\'\']', " ", claim_text).strip()
    words = [
        w
        for w in re.split(r"\s+", clean)
        if len(w) >= 3
        and w.lower()
        not in {
            "que",
            "com",
            "para",
            "por",
            "uma",
            "uns",
            "das",
            "dos",
            "sobre",
            "esse",
            "esta",
            "como",
            "este",
            "pelo",
            "pela",
        }
    ]
    core_phrase = " ".join(words[:7])
    if not core_phrase:
        core_phrase = clean[:60]

    return [
        f"{core_phrase} (fato ou fake OR boato OR desmentido OR checagem)",
        f"é verdade {core_phrase}",
        f"{core_phrase} site:aosfatos.org OR site:lupa.news OR site:boatos.org",
    ]
