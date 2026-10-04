"""Free DuckDuckGo web search adapter requiring zero API keys."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from harness_agent.web.models import WebSearchResult
from harness_agent.web.safe_http import DEFAULT_USER_AGENT, check_url

DDG_HTML_URL = "https://html.duckduckgo.com/html/"


def _clean_ddg_url(raw_url: str) -> str:
    """Extract real destination URL from DuckDuckGo redirect link."""
    if not raw_url:
        return ""
    if "uddg=" in raw_url:
        parsed = urlparse(raw_url)
        params = parse_qs(parsed.query)
        if "uddg" in params and params["uddg"]:
            return unquote(params["uddg"][0])
        # Regex fallback for uddg parameter
        match = re.search(r"uddg=([^&]+)", raw_url)
        if match:
            return unquote(match.group(1))

    if raw_url.startswith("//"):
        return "https:" + raw_url
    return raw_url


class _DuckDuckGoHTMLParser(HTMLParser):
    """Parse DuckDuckGo HTML search results page."""

    def __init__(self, max_results: int = 5) -> None:
        super().__init__()
        self.max_results = max_results
        self.results: List[WebSearchResult] = []

        self._in_result_a = False
        self._in_snippet = False
        self._current_url = ""
        self._current_title: List[str] = []
        self._current_snippet: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if len(self.results) >= self.max_results:
            return

        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        classes = attr_dict.get("class", "").split()

        if tag == "a" and "result__a" in classes:
            self._in_result_a = True
            raw_href = attr_dict.get("href", "")
            self._current_url = _clean_ddg_url(raw_href)
            self._current_title = []
            return

        if (tag in ("a", "div", "span")) and ("result__snippet" in classes):
            self._in_snippet = True
            self._current_snippet = []
            return

    def handle_endtag(self, tag: str) -> None:
        if self._in_result_a and tag == "a":
            self._in_result_a = False
            return

        if self._in_snippet and tag in ("a", "div", "span"):
            self._in_snippet = False
            if self._current_url and self._current_title:
                title = unescape(" ".join(self._current_title)).strip()
                snippet = unescape(" ".join(self._current_snippet)).strip()
                # Clean multiple whitespaces
                title = re.sub(r"\s+", " ", title)
                snippet = re.sub(r"\s+", " ", snippet)

                if title and self._current_url:
                    self.results.append(
                        WebSearchResult(
                            title=title,
                            url=self._current_url,
                            snippet=snippet,
                            provider="duckduckgo",
                            rank=len(self.results) + 1,
                        )
                    )
                self._current_url = ""
                self._current_title = []
                self._current_snippet = []
            return

    def handle_data(self, data: str) -> None:
        if self._in_result_a:
            self._current_title.append(data)
        elif self._in_snippet:
            self._current_snippet.append(data)


def parse_ddg_html(html: str, max_results: int = 5) -> List[WebSearchResult]:
    """Parse DuckDuckGo HTML output into structured WebSearchResult items."""
    parser = _DuckDuckGoHTMLParser(max_results=max_results)
    parser.feed(html)
    if parser.results:
        return parser.results[:max_results]

    # Regex fallback if markup structure differs
    results: List[WebSearchResult] = []
    blocks = re.findall(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<(?:a|div|span)[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div|span)>',
        html,
        re.DOTALL,
    )
    for raw_url, raw_title, raw_snippet in blocks[:max_results]:
        url = _clean_ddg_url(raw_url)
        title = re.sub(r"<[^>]+>", "", unescape(raw_title)).strip()
        snippet = re.sub(r"<[^>]+>", "", unescape(raw_snippet)).strip()
        if url and title:
            results.append(
                WebSearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    provider="duckduckgo",
                    rank=len(results) + 1,
                )
            )

    return results


def search_duckduckgo(
    query: str,
    max_results: int = 5,
    timeout: float = 15.0,
) -> List[WebSearchResult]:
    """Execute a free web search against DuckDuckGo without any API key.

    Args:
        query: Search keywords or query string.
        max_results: Number of organic results to retrieve.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of WebSearchResult objects.
    """
    check_url(DDG_HTML_URL)
    url = f"{DDG_HTML_URL}?q={quote_plus(query)}"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code >= 400:
            # Try POST if GET is blocked or rate limited
            resp = client.post(DDG_HTML_URL, data={"q": query}, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"DuckDuckGo search returned HTTP {resp.status_code} for query: {query}"
                )

        return parse_ddg_html(resp.text, max_results=max_results)
