"""Heuristic detection of cookie walls and paywalls (RF-04.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MIN_USEFUL_CHARS = 300

_COOKIE_PHRASES = re.compile(
    r"(aceitar (todos os )?cookies|usamos cookies|utilizamos cookies|este site usa cookies|"
    r"política de cookies|gerenciar (as )?preferências|consentimento de cookies|"
    r"we use cookies|this (web)?site uses cookies|accept (all )?cookies|cookie (policy|settings|preferences)|"
    r"manage (your )?(cookie|consent|privacy) (preferences|settings)|reject all|"
    r"usamos cookies para|aceito os termos)",
    re.IGNORECASE,
)
_CMP_MARKERS = re.compile(
    r"(onetrust|didomi|cookiebot|osano|trustarc|quantcast|cmp-container|cookie-consent|"
    r"cookie-banner|cookiebanner|gdpr-consent|lgpd-banner)",
    re.IGNORECASE,
)
_PAYWALL_PHRASES = re.compile(
    r"(assine para (continuar|ler|ter acesso)|para continuar lendo|conteúdo (exclusivo )?para assinantes|"
    r"já é assinante|seja assinante|restante do (conteúdo|texto) (é )?(exclusivo|restrito)|"
    r"subscribe to (continue|read|unlock)|subscribers? only|sign in to (continue )?read|"
    r"you('ve| have) reached your (free )?(article )?limit|create a free account to continue|"
    r"become a (member|subscriber) to (read|continue))",
    re.IGNORECASE,
)
_PAYWALL_MARKERS = re.compile(
    r"(class|id)=[\"'][^\"']*(paywall|premium-content|subscriber-only|subscription-wall|piano-offer)",
    re.IGNORECASE,
)
_JSONLD_NOT_FREE = re.compile(r"\"isAccessibleForFree\"\s*:\s*\"?false", re.IGNORECASE)


@dataclass(frozen=True)
class Blocker:
    kind: Literal["cookies", "paywall"]
    blocking: bool  # True: no useful content could be extracted at all
    detail: str


def detect_blockers(html: str, text: str) -> list[Blocker]:
    text = text or ""
    n = len(text)
    found: list[Blocker] = []

    cookie_chars = sum(len(m.group(0)) for m in _COOKIE_PHRASES.finditer(text))
    has_cmp = bool(_CMP_MARKERS.search(html or ""))
    cookie_dominated = n > 0 and cookie_chars / n > 0.25
    if (n < 600 and (cookie_chars > 0 or (has_cmp and n < MIN_USEFUL_CHARS))) or cookie_dominated:
        found.append(
            Blocker(
                "cookies",
                blocking=n < MIN_USEFUL_CHARS or cookie_dominated,
                detail="Banner/parede de consentimento de cookies detectado no conteúdo extraído.",
            )
        )

    jsonld = bool(_JSONLD_NOT_FREE.search(html or ""))
    phrase = bool(_PAYWALL_PHRASES.search(text)) or bool(_PAYWALL_PHRASES.search(html or "")) and n < 3000
    marker = bool(_PAYWALL_MARKERS.search(html or "")) and n < 5000
    if jsonld or (phrase and n < 3000) or marker:
        found.append(
            Blocker(
                "paywall",
                blocking=n < MIN_USEFUL_CHARS,
                detail="Paywall/conteúdo restrito a assinantes detectado; a análise cobre só o trecho aberto.",
            )
        )
    return found
