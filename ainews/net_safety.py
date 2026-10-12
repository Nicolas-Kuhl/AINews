"""Guard for fetching URLs that come from untrusted content.

Article links arrive from RSS entries, search results and — via Claude —
the bodies of inbound newsletter emails, whose From header anyone can forge.
Fetching them from the server (article text, page screenshots) must not
reach the server's own network: localhost services, the VPC, or the EC2
instance-metadata endpoint. Every hop (including redirects) is checked.

Resolution happens again inside the HTTP client, so a DNS-rebinding race
remains possible; enforcing IMDSv2 with a hop limit of 1 on the instance is
the defence in depth for the metadata endpoint.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import urlparse


def _system_resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop IPv6 zone id
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def is_public_url(url: str, resolve: Callable[[str], Iterable[str]] = _system_resolve) -> bool:
    """True only for an http(s) URL whose host resolves solely to public IPs."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname
    try:
        addresses = [host] if _looks_like_ip(host) else list(resolve(host))
        return bool(addresses) and all(_is_public_ip(a) for a in addresses)
    except (OSError, ValueError, UnicodeError):
        return False


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def safe_http_url(url) -> str:
    """``url`` if it is an http(s) link with a host, else "".

    For links rendered into the dashboard and the newsletter: anything else
    (``javascript:``, ``data:``, the synthetic ``newsletter://`` ids) must not
    become a clickable href.
    """
    if not isinstance(url, str):
        return ""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
        return url.strip()
    return ""
