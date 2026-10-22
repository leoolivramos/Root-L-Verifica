"""SSRF-safe HTTP fetcher: validates every hop, pins the connection to a validated IP."""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from reliability.errors import FetchError, UnsafeURL
from reliability.ingestion.ssrf import resolve_public_ips

USER_AGENT = (
    "Mozilla/5.0 (compatible; ReliabilityLab/0.1; +local personal analysis tool) "
    "AppleWebKit/537.36 (KHTML, like Gecko)"
)
IMAGE_CONTENT_TYPES = (
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/avif",
)
VIDEO_CONTENT_TYPES = (
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "video/ogg",
)
ALLOWED_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    *IMAGE_CONTENT_TYPES,
    *VIDEO_CONTENT_TYPES,
)

Resolver = Callable[[str], Awaitable[list[str]]]


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status_code: int
    content_type: str
    text: str
    raw_bytes: bytes = b""
    truncated: bool = False


class SafeFetcher:
    def __init__(
        self,
        *,
        max_bytes: int = 2_000_000,
        timeout_s: float = 15.0,
        max_redirects: int = 5,
        allowed_ports: tuple[int, ...] = (80, 443, 8080, 8443),
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.max_bytes = max_bytes
        self.timeout_s = timeout_s
        self.max_redirects = max_redirects
        self.allowed_ports = allowed_ports
        self._resolver = resolver or (lambda u: resolve_public_ips(u, allowed_ports))
        self._transport = transport
        # Pin to the validated IP only when talking to the real network.
        self._pin = transport is None

    async def fetch(self, url: str) -> FetchResult:
        current = url
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(self.timeout_s),
            follow_redirects=False,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
            },
        ) as client:
            for _ in range(self.max_redirects + 1):
                ips = await self._resolver(current)  # raises UnsafeURL
                request_url, headers, ext = self._prepare(current, ips[0])
                try:
                    async with client.stream(
                        "GET", request_url, headers=headers, extensions=ext
                    ) as resp:
                        if resp.is_redirect:
                            loc = resp.headers.get("location")
                            if not loc:
                                raise FetchError("Redirecionamento inválido (sem destino).")
                            current = urljoin(current, loc)
                            continue
                        return await self._read(resp, current)
                except UnsafeURL:
                    raise
                except httpx.TimeoutException as exc:
                    raise FetchError("Tempo esgotado ao acessar a página.") from exc
                except httpx.HTTPError as exc:
                    raise FetchError(f"Não foi possível acessar a página ({type(exc).__name__}).") from exc
        raise FetchError("Redirecionamentos demais.")

    def _prepare(self, url: str, ip: str) -> tuple[str, dict[str, str], dict]:
        if not self._pin:
            return url, {}, {}
        parts = urlsplit(url)
        host = parts.hostname or ""
        try:
            ipaddress.ip_address(host.strip("[]"))
            return url, {}, {}  # already a literal IP
        except ValueError:
            pass
        netloc_ip = f"[{ip}]" if ":" in ip else ip
        if parts.port:
            netloc_ip += f":{parts.port}"
        pinned = urlunsplit((parts.scheme, netloc_ip, parts.path or "/", parts.query, ""))
        host_header = host + (f":{parts.port}" if parts.port else "")
        ext = {"sni_hostname": host} if parts.scheme == "https" else {}
        return pinned, {"Host": host_header}, ext

    async def _read(self, resp: httpx.Response, final_url: str) -> FetchResult:
        if resp.status_code in (401, 402, 403, 451):
            raise FetchError(
                f"O site negou o acesso automatizado (HTTP {resp.status_code}). "
                "Pode haver bloqueio, paywall ou login obrigatório."
            )
        if resp.status_code == 404 or resp.status_code == 410:
            raise FetchError(f"Página não encontrada (HTTP {resp.status_code}).")
        if resp.status_code >= 400:
            raise FetchError(f"O site respondeu com erro (HTTP {resp.status_code}).")
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype and not ctype.startswith(ALLOWED_CONTENT_TYPES):
            raise FetchError(f"Tipo de conteúdo não suportado ({ctype}). Use páginas HTML ou texto.")
        chunks: list[bytes] = []
        total = 0
        truncated = False
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                keep = len(chunk) - (total - self.max_bytes)
                chunks.append(chunk[:keep])
                truncated = True
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        is_binary = any(ctype.startswith(t) for t in (*IMAGE_CONTENT_TYPES, *VIDEO_CONTENT_TYPES))
        text = ""
        if not is_binary:
            encoding = resp.charset_encoding or "utf-8"
            try:
                text = raw.decode(encoding, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
        return FetchResult(final_url, resp.status_code, ctype, text, raw, truncated)
