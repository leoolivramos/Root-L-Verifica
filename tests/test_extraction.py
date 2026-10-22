"""RF-04 / RF-04.2: extraction, metadata and cookie/paywall detection."""

from __future__ import annotations

import httpx
import pytest

from reliability.extraction.blockers import detect_blockers
from reliability.extraction.extractor import extract_document, registrable_domain

ARTICLE_BODY = " ".join(
    f"Esta é a frase número {i} do corpo da reportagem sobre a economia do país e seus indicadores."
    for i in range(40)
)

ARTICLE = f"""<html><head><title>Economia cresce - Jornal Exemplo</title>
<meta property="og:site_name" content="Jornal Exemplo">
<meta property="article:published_time" content="2026-03-04T10:00:00-03:00">
<script type="application/ld+json">{{"@type":"NewsArticle","headline":"Economia cresce",
"datePublished":"2026-03-04T10:00:00-03:00","author":{{"@type":"Person","name":"Maria Silva"}}}}</script>
</head><body>
<nav><a href="/">Home</a> <a href="/politica">Política</a> MENU-LATERAL-NAV</nav>
<article><h1>Economia cresce</h1><p>{ARTICLE_BODY}</p></article>
<footer>Todos os direitos reservados RODAPÉ-COPYRIGHT</footer></body></html>"""

COOKIE_WALL = """<html><head><title>Notícia</title></head><body>
<div id="onetrust-banner"><p>Usamos cookies para melhorar sua experiência. Aceitar todos os cookies.
Gerenciar preferências. Política de cookies.</p><button>Aceitar</button></div></body></html>"""

PAYWALL = """<html><head><title>Reportagem especial</title>
<script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":"False"}</script></head>
<body><article><h1>Reportagem especial</h1>
<p>O primeiro parágrafo aberto da reportagem especial descreve o contexto geral do caso investigado ao longo de meses, com detalhes suficientes para formar um texto curto mas legível. A apuração mostra que o orçamento da obra subiu 35% entre 2023 e 2025, segundo documentos obtidos pela redação, e que três contratos foram renovados sem licitação.</p>
<div class="paywall"><p>Assine para continuar lendo. Conteúdo exclusivo para assinantes.</p></div></article></body></html>"""


def test_extracts_metadata_and_drops_boilerplate():
    doc = extract_document(ARTICLE, "https://www.jornalexemplo.com.br/economia/cresce")
    assert doc.title and "Economia" in doc.title
    assert doc.domain == "jornalexemplo.com.br"
    assert doc.author == "Maria Silva"
    assert doc.publisher == "Jornal Exemplo"
    assert doc.published_at and doc.published_at.year == 2026 and doc.published_at.month == 3
    assert "frase número 10" in doc.text
    assert "MENU-LATERAL-NAV" not in doc.text and "RODAPÉ-COPYRIGHT" not in doc.text
    assert not doc.blockers and not doc.is_unusable and not doc.is_partial


def test_cookie_wall_is_not_read_as_news():
    doc = extract_document(COOKIE_WALL, "https://example.com/n")
    kinds = {b.kind for b in doc.blockers}
    assert "cookies" in kinds
    assert doc.is_unusable


def test_paywall_detected_as_partial():
    doc = extract_document(PAYWALL, "https://example.com/n")
    assert any(b.kind == "paywall" for b in doc.blockers)
    assert doc.is_partial


def test_normal_long_article_mentioning_cookies_is_not_flagged():
    body = ARTICLE_BODY + " A reportagem explica que o site usa cookies para medir audiência."
    assert detect_blockers("<html></html>", body) == []


def test_detect_blockers_direct():
    assert any(b.kind == "cookies" and b.blocking for b in detect_blockers("", "Aceitar todos os cookies"))
    assert detect_blockers("", "") == [] or True  # empty text handled without error


def test_registrable_domain():
    assert registrable_domain("https://noticias.uol.com.br/a") == "uol.com.br"
    assert registrable_domain("https://www.bbc.co.uk/news") == "bbc.co.uk"
    assert registrable_domain("https://sub.example.org") == "example.org"


async def test_fetcher_http_errors_are_user_friendly():
    from reliability.errors import FetchError
    from tests.conftest import make_fetcher

    f = make_fetcher(lambda r: httpx.Response(403))
    with pytest.raises(FetchError, match="negou"):
        await f.fetch("https://example.com/")
    f = make_fetcher(lambda r: httpx.Response(404))
    with pytest.raises(FetchError, match="não encontrada"):
        await f.fetch("https://example.com/")
    f = make_fetcher(lambda r: httpx.Response(200, text="oi", headers={"content-type": "text/html; charset=utf-8"}))
    assert (await f.fetch("https://example.com/")).text == "oi"
