"""Main-content extraction with Trafilatura, falling back to BeautifulSoup heuristics."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit

import tldextract
import trafilatura
from bs4 import BeautifulSoup

from reliability.extraction.blockers import Blocker, detect_blockers

_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)  # offline: bundled snapshot


def registrable_domain(url_or_host: str) -> str:
    host = urlsplit(url_or_host).hostname if "://" in url_or_host else url_or_host
    host = (host or "").lower()
    ext = _TLD(host)
    return ext.top_domain_under_public_suffix or host


@dataclass
class ExtractedDocument:
    url: str | None
    title: str | None = None
    domain: str | None = None
    published_at: datetime | None = None
    author: str | None = None
    publisher: str | None = None
    text: str = ""
    metadata: dict = field(default_factory=dict)
    blockers: list[Blocker] = field(default_factory=list)
    media_type: str | None = None
    media_url: str | None = None

    @property
    def is_partial(self) -> bool:
        return bool(self.blockers)

    @property
    def is_unusable(self) -> bool:
        return any(b.blocking for b in self.blockers) or len(self.text.strip()) < 80


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    return None


def _jsonld_meta(soup: BeautifulSoup) -> dict:
    out: dict = {}
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            t = " ".join(t) if isinstance(t, list) else str(t or "")
            if "Article" in t or "NewsArticle" in t or "BlogPosting" in t:
                out.setdefault("headline", it.get("headline"))
                out.setdefault("datePublished", it.get("datePublished"))
                author = it.get("author")
                if isinstance(author, list) and author:
                    author = author[0]
                if isinstance(author, dict):
                    author = author.get("name")
                out.setdefault("author", author if isinstance(author, str) else None)
                pub = it.get("publisher")
                if isinstance(pub, dict):
                    out.setdefault("publisher", pub.get("name"))
    return out


def _fallback_text(soup: BeautifulSoup) -> str:
    for t in soup(["script", "style", "noscript", "nav", "footer", "aside", "form", "header", "iframe"]):
        t.decompose()
    container = soup.find("article") or soup.find("main") or soup.body or soup
    paras = [p.get_text(" ", strip=True) for p in container.find_all(["p", "h1", "h2", "h3", "li"])]
    paras = [p for p in paras if len(p) > 40]
    return "\n\n".join(paras)


def extract_document(html: str, url: str) -> ExtractedDocument:
    soup_meta = BeautifulSoup(html, "lxml")
    ld = _jsonld_meta(soup_meta)

    title = author = publisher = date_s = None
    text = ""
    try:
        doc = trafilatura.bare_extraction(
            html, url=url, with_metadata=True, favor_precision=True, include_comments=False
        )
    except Exception:  # noqa: BLE001 - trafilatura can raise on malformed input
        doc = None
    if doc is not None:
        get = (lambda k: getattr(doc, k, None)) if not isinstance(doc, dict) else doc.get
        text = (get("text") or "").strip()
        title, author, publisher, date_s = get("title"), get("author"), get("sitename"), get("date")

    if len(text) < 200:  # trafilatura found little: try the heuristic fallback
        fb = _fallback_text(BeautifulSoup(html, "lxml"))
        if len(fb) > len(text):
            text = fb

    if not title:
        title = ld.get("headline") or (
            soup_meta.title.get_text(strip=True) if soup_meta.title else None
        )
    author = author or ld.get("author")
    publisher = publisher or ld.get("publisher")
    if not publisher:
        og = soup_meta.find("meta", attrs={"property": "og:site_name"})
        publisher = og.get("content") if og else None
    date_s = date_s or ld.get("datePublished")
    if not date_s:
        m = soup_meta.find("meta", attrs={"property": "article:published_time"})
        date_s = m.get("content") if m else None

    og_img = soup_meta.find("meta", attrs={"property": "og:image"}) or soup_meta.find(
        "meta", attrs={"name": "twitter:image"}
    )
    featured_img = og_img.get("content") if og_img else None
    if featured_img and not (featured_img.startswith("http://") or featured_img.startswith("https://")):
        from urllib.parse import urljoin
        featured_img = urljoin(url, featured_img)

    domain = registrable_domain(url)
    return ExtractedDocument(
        url=url,
        title=(title or None),
        domain=domain,
        published_at=_parse_date(date_s),
        author=(author or None),
        publisher=(publisher or None),
        text=text,
        metadata={"jsonld": ld, "raw_date": date_s},
        blockers=detect_blockers(html, text),
        media_type="image" if featured_img else None,
        media_url=featured_img if featured_img else None,
    )


def document_from_text(text: str) -> ExtractedDocument:
    return ExtractedDocument(url=None, title=None, domain=None, text=text.strip())
