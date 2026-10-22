"""SSRF protection (RNF-04): only public, global IPs on allowed ports."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from reliability.errors import UnsafeURL

ALLOWED_PORTS_DEFAULT = (80, 443, 8080, 8443)

_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet")


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when the address is not a publicly routable (global) unicast address."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_blocked_ip(ip.ipv4_mapped)
        if ip.sixtofour is not None and is_blocked_ip(ip.sixtofour):
            return True
        # NAT64 well-known prefix: embedded IPv4 must itself be public
        if ip in ipaddress.ip_network("64:ff9b::/96"):
            return is_blocked_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return True
    # CGNAT (100.64.0.0/10) is not "global" in recent Pythons, but be explicit.
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return True
    return False


def _check_static(url: str, allowed_ports: tuple[int, ...]) -> tuple[str, int]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Somente URLs http:// ou https:// são permitidas.")
    if parts.username or parts.password or "@" in parts.netloc:
        raise UnsafeURL("URLs com credenciais embutidas (usuario@host) são bloqueadas.")
    host = (parts.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise UnsafeURL("URL sem host válido.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURL("Porta inválida na URL.") from exc
    if port not in allowed_ports:
        raise UnsafeURL(f"Porta {port} não permitida (permitidas: {', '.join(map(str, allowed_ports))}).")
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURL("Destino local/interno bloqueado por segurança.")
    return host, port


async def resolve_public_ips(
    url: str, allowed_ports: tuple[int, ...] = ALLOWED_PORTS_DEFAULT
) -> list[str]:
    """Validate `url` and return the (all-public) IPs its host resolves to.

    Raises UnsafeURL if the scheme/port/host is disallowed, or if ANY resolved
    address is private/loopback/link-local/reserved.
    """
    host, port = _check_static(url, allowed_ports)

    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if is_blocked_ip(literal):
            raise UnsafeURL("Endereço IP privado, local ou reservado bloqueado por segurança.")
        return [str(literal)]

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURL(f"Não foi possível resolver o endereço '{host}'.") from exc
    ips: list[str] = []
    for info in infos:
        addr = info[4][0].split("%")[0]
        ip = ipaddress.ip_address(addr)
        if is_blocked_ip(ip):
            raise UnsafeURL(
                "O endereço resolve para uma rede privada/local e foi bloqueado por segurança."
            )
        if addr not in ips:
            ips.append(addr)
    if not ips:
        raise UnsafeURL(f"Sem endereços para '{host}'.")
    return ips


async def assert_public_url(
    url: str, allowed_ports: tuple[int, ...] = ALLOWED_PORTS_DEFAULT
) -> None:
    await resolve_public_ips(url, allowed_ports)
