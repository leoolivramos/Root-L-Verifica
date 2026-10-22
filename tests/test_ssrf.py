"""RNF-04: SSRF protection."""

from __future__ import annotations

import httpx
import pytest

from reliability.errors import UnsafeURL
from reliability.extraction.fetcher import SafeFetcher
from reliability.ingestion.ssrf import assert_public_url, resolve_public_ips


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.1.2.3:8080/x",
        "http://10.0.0.5/",
        "http://172.16.4.4/",
        "http://192.168.1.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://localhost/",
        "http://foo.localhost/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://printer.local/",
        "http://example.com@evil.test/",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://example.com:22/",
        "http://example.com:6379/",
        "http:///nohost",
    ],
)
async def test_blocked(url):
    with pytest.raises(UnsafeURL):
        await assert_public_url(url)


async def test_public_literal_ip_allowed():
    assert await resolve_public_ips("https://93.184.216.34/page") == ["93.184.216.34"]


async def test_dns_resolving_to_private_is_blocked(monkeypatch):
    import asyncio

    async def fake_getaddrinfo(self, host, port, **kw):
        return [(2, 1, 6, "", ("192.168.0.10", port)), (2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(asyncio.get_running_loop().__class__, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURL):
        await assert_public_url("https://rebind.example.test/")


async def test_redirect_to_private_ip_is_blocked():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, text="secret")

    async def resolver(url: str):
        from reliability.ingestion.ssrf import resolve_public_ips as real

        if "public.example" in url:
            return ["93.184.216.34"]
        return await real(url)

    fetcher = SafeFetcher(transport=httpx.MockTransport(handler), resolver=resolver)
    with pytest.raises(UnsafeURL):
        await fetcher.fetch("https://public.example/start")
    assert all("169.254" not in c for c in calls)  # the private hop was never requested


async def test_too_many_redirects():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://public.example/loop"})

    async def resolver(url):
        return ["93.184.216.34"]

    from reliability.errors import FetchError

    f = SafeFetcher(transport=httpx.MockTransport(handler), resolver=resolver, max_redirects=3)
    with pytest.raises(FetchError):
        await f.fetch("https://public.example/loop")


async def test_content_type_and_size_limits():
    from reliability.errors import FetchError

    async def resolver(url):
        return ["93.184.216.34"]

    f = SafeFetcher(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
        ),
        resolver=resolver,
    )
    with pytest.raises(FetchError):
        await f.fetch("https://x.example/doc.pdf")

    big = SafeFetcher(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"a" * 5000, headers={"content-type": "text/html"})
        ),
        resolver=resolver,
        max_bytes=1000,
    )
    res = await big.fetch("https://x.example/big")
    assert res.truncated and len(res.text) == 1000
