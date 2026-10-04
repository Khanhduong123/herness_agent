"""SSRF-safe HTTP helper for outbound fetches.

Validates URLs and destination IP addresses to prevent SSRF vulnerabilities:
- Restricts schemes strictly to http and https.
- Resolves hostnames and rejects private, loopback, link-local, multicast,
  reserved, unspecified, and cloud metadata (e.g. 169.254.169.254) addresses.
- Enforces manual hop-by-hop redirect validation (up to 5 hops).
- Streams responses under a configurable size cap (default 10MB) to mitigate zip/memory bombs.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

_ALLOWED_SCHEMES = frozenset({"http", "https"})

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 harness-agent/0.1"
)

MAX_BYTES_HTML = 10 * 1024 * 1024
MAX_BYTES_PDF = 25 * 1024 * 1024
MAX_BYTES_IMAGE = 2 * 1024 * 1024


class SafeHTTPError(Exception):
    """The SSRF gate refused this request, or the response exceeded a limit."""


class CertVerificationError(SafeHTTPError):
    """TLS certificate verification failed."""


class SafeResponse(BaseModel):
    """Minimal SSRF-safe response wrapper avoiding leaking httpx internals."""

    url: str
    status_code: int
    headers: Dict[str, str] = Field(default_factory=dict)
    content: bytes = Field(default=b"", repr=False)

    @property
    def text(self) -> str:
        charset = "utf-8"
        ct = self.headers.get("content-type", "")
        if "charset=" in ct.lower():
            charset = ct.lower().split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")
_6TO4_NET = ipaddress.ip_network("2002::/16")


def _is_blocked_ip(ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    ip = getattr(ip, "ipv4_mapped", None) or ip
    if ip.version == 6 and ip in _6TO4_NET:
        packed = int(ip) >> 80 & 0xFFFFFFFF
        return _is_blocked_ip(ipaddress.IPv4Address(packed))
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 4 and ip in _CGNAT_NET)
    )


def _resolve(host: str) -> List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SafeHTTPError(f"DNS lookup failed for {host!r}: {exc}") from exc
    addrs: List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]] = []
    for info in infos:
        try:
            addrs.append(ipaddress.ip_address(info[4][0]))
        except (ValueError, IndexError):
            continue
    return addrs


def _parse_allowlist(
    entries: Sequence[str],
) -> Tuple[frozenset[str], List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]]]:
    hostnames: set[str] = set()
    networks: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry.strip("[]"), strict=False))
        except ValueError:
            if "/" in entry:
                raise SafeHTTPError(
                    f"invalid allow_private_hosts entry {entry!r}: not a valid CIDR"
                ) from None
            if ":" in entry:
                raise SafeHTTPError(
                    f"invalid allow_private_hosts entry {entry!r}: entries are "
                    "hostnames or CIDRs; drop the port"
                )
            hostnames.add(entry.lower())
    return frozenset(hostnames), networks


def check_url(url: str, allow_private_hosts: Sequence[str] = ()) -> None:
    """Validate that the URL is safe to fetch and does not resolve to private addresses.

    Raises:
        SafeHTTPError: If URL uses forbidden scheme, has no hostname, or resolves to private IP.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise SafeHTTPError(
            f"refusing URL with scheme {parsed.scheme!r}; only http/https are allowed"
        )
    if not parsed.hostname:
        raise SafeHTTPError(f"refusing URL with no hostname: {url!r}")
    allowed_hosts, allowed_nets = _parse_allowlist(allow_private_hosts)
    if parsed.hostname.lower() in allowed_hosts:
        return
    addrs = _resolve(parsed.hostname)
    if not addrs:
        raise SafeHTTPError(f"refusing URL {url!r}: hostname did not resolve")
    for addr in addrs:
        if _is_blocked_ip(addr) and not any(
            addr.version == net.version and addr in net for net in allowed_nets
        ):
            raise SafeHTTPError(
                f"refusing URL {url!r}: hostname {parsed.hostname} resolves to "
                f"non-public address {addr}"
            )


def safe_get(
    url: str,
    *,
    max_bytes: int = MAX_BYTES_HTML,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    headers: Optional[Dict[str, str]] = None,
    verify: Union[bool, str] = True,
    allow_private_hosts: Sequence[str] = (),
    transport: Optional[httpx.BaseTransport] = None,
) -> SafeResponse:
    """GET URL with SSRF, redirect revalidation, and response size protections.

    Args:
        url: Target HTTP or HTTPS URL.
        max_bytes: Maximum allowed payload in bytes.
        timeout: Network timeout in seconds.
        max_redirects: Maximum allowed redirect hops.
        headers: Optional HTTP headers dict.
        verify: SSL verification flag or CA bundle path.
        allow_private_hosts: List of allowlisted hosts or CIDRs.
        transport: Test seam transport (e.g. MockTransport).

    Returns:
        SafeResponse instance.

    Raises:
        SafeHTTPError: If request violates security policies or size limits.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be > 0")

    request_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        request_headers.update(headers)

    current_url = url
    try:
        with httpx.Client(
            follow_redirects=False, timeout=timeout, verify=verify, transport=transport
        ) as client:
            for _ in range(max_redirects + 1):
                check_url(current_url, allow_private_hosts)
                with client.stream("GET", current_url, headers=request_headers) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            return _materialize(resp, b"", current_url)
                        current_url = str(httpx.URL(current_url).join(location))
                        continue

                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise SafeHTTPError(
                            f"refusing response from {current_url!r}: "
                            f"Content-Length {declared} exceeds cap {max_bytes}"
                        )

                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise SafeHTTPError(
                                f"refusing response from {current_url!r}: "
                                f"body exceeds cap {max_bytes} bytes"
                            )
                    return _materialize(resp, bytes(body), current_url)

        raise SafeHTTPError(f"too many redirects (>{max_redirects}) starting at {url!r}")
    except httpx.ConnectError as exc:
        err_msg = str(exc).lower()
        if "certificate" in err_msg or "ssl" in err_msg:
            raise CertVerificationError(
                f"certificate verification failed for {current_url!r}: {exc}"
            ) from exc
        raise


def _materialize(resp: httpx.Response, body: bytes, final_url: str) -> SafeResponse:
    return SafeResponse(
        url=final_url,
        status_code=resp.status_code,
        headers={k.lower(): v for k, v in resp.headers.items()},
        content=body,
    )
