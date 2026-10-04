"""Web crawling, searching, and SSRF-safe HTTP capabilities for Harness Agent."""

from __future__ import annotations

from harness_agent.web.builtin import BuiltinProvider
from harness_agent.web.crawl4ai_provider import Crawl4AIProvider
from harness_agent.web.free_search import parse_ddg_html, search_duckduckgo
from harness_agent.web.models import WebResult, WebSearchResult
from harness_agent.web.safe_http import (
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_TIMEOUT,
    MAX_BYTES_HTML,
    CertVerificationError,
    SafeHTTPError,
    SafeResponse,
    check_url,
    safe_get,
)

__all__ = [
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_TIMEOUT",
    "MAX_BYTES_HTML",
    "BuiltinProvider",
    "CertVerificationError",
    "Crawl4AIProvider",
    "SafeHTTPError",
    "SafeResponse",
    "WebResult",
    "WebSearchResult",
    "check_url",
    "parse_ddg_html",
    "safe_get",
    "search_duckduckgo",
]
