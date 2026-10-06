"""Tests for SSRF-safe HTTP client."""

from __future__ import annotations

import httpx
import pytest

from harness_agent.web.safe_http import SafeHTTPError, SafeResponse, check_url, safe_get


def test_scheme_validation() -> None:
    with pytest.raises(SafeHTTPError, match="only http/https"):
        check_url("ftp://example.com")

    with pytest.raises(SafeHTTPError, match="only http/https"):
        check_url("file:///etc/passwd")

    with pytest.raises(SafeHTTPError, match="only http/https"):
        check_url("gopher://evil.com")


def test_missing_hostname() -> None:
    with pytest.raises(SafeHTTPError, match="no hostname"):
        check_url("http://")


def test_blocked_private_and_loopback_ips() -> None:
    blocked_urls = [
        "http://127.0.0.1",
        "http://127.0.0.2:8080",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254",  # AWS/GCP metadata
        "http://[::1]",
        "http://[::ffff:127.0.0.1]",
        "http://100.64.0.1",  # CGNAT
        "http://[2002:7f00:1::]",  # 6to4 loopback
    ]
    for url in blocked_urls:
        with pytest.raises(SafeHTTPError, match="resolves to non-public address"):
            check_url(url)


def test_allowlist_matching() -> None:
    # Bare IP allowlist
    check_url("http://127.0.0.1", allow_private_hosts=["127.0.0.1"])

    # CIDR allowlist
    check_url("http://192.168.1.42", allow_private_hosts=["192.168.1.0/24"])

    # Hostname allowlist
    check_url("http://internal-wiki.local", allow_private_hosts=["internal-wiki.local"])


def test_malformed_allowlist_entries() -> None:
    with pytest.raises(SafeHTTPError, match="not a valid CIDR"):
        check_url("http://example.com", allow_private_hosts=["10.0.0.1/999"])

    with pytest.raises(SafeHTTPError, match="drop the port"):
        check_url("http://example.com", allow_private_hosts=["localhost:8080"])


def test_safe_get_size_cap_declared() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "2000"},
            content=b"x" * 2000,
        )

    transport = httpx.MockTransport(handler)
    with pytest.raises(SafeHTTPError, match="Content-Length 2000 exceeds cap 1000"):
        safe_get(
            "http://127.0.0.1",
            max_bytes=1000,
            allow_private_hosts=["127.0.0.1"],
            transport=transport,
        )


def test_safe_get_size_cap_streamed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        def stream_gen():
            for _ in range(5):
                yield b"A" * 1000

        # Generator content avoids automatic Content-Length calculation
        return httpx.Response(200, content=stream_gen())

    transport = httpx.MockTransport(handler)
    with pytest.raises(SafeHTTPError, match="body exceeds cap 1000 bytes"):
        safe_get(
            "http://127.0.0.1",
            max_bytes=1000,
            allow_private_hosts=["127.0.0.1"],
            transport=transport,
        )


def test_safe_get_redirect_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/redirect-loop"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(SafeHTTPError, match="too many redirects"):
        safe_get(
            "http://127.0.0.1/loop",
            max_bytes=5000,
            max_redirects=3,
            allow_private_hosts=["127.0.0.1"],
            transport=transport,
        )


def test_safe_get_redirect_to_disallowed_ip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Redirect from allowed host to private host
        return httpx.Response(302, headers={"Location": "http://10.0.0.1/admin"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(SafeHTTPError, match="resolves to non-public address"):
        safe_get(
            "http://127.0.0.1/jump",
            max_bytes=5000,
            allow_private_hosts=["127.0.0.1"],  # 10.0.0.1 is NOT allowlisted
            transport=transport,
        )


def test_safe_get_success_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b"<html><body><h1>Hello World</h1></body></html>",
        )

    transport = httpx.MockTransport(handler)
    resp: SafeResponse = safe_get(
        "http://127.0.0.1/ok",
        max_bytes=5000,
        allow_private_hosts=["127.0.0.1"],
        transport=transport,
    )
    assert resp.status_code == 200
    assert "<h1>Hello World</h1>" in resp.text
    assert resp.url == "http://127.0.0.1/ok"
