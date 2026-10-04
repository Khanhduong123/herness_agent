"""Local Crawl4AI web provider — 100% free, zero-API-key headless Chromium crawler.

Renders complex JavaScript and SPAs, handles dynamic DOM stability waiting,
and extracts clean markdown with automated fallback to BuiltinProvider.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import threading
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence
from urllib.parse import urlparse

from harness_agent.web.builtin import BuiltinProvider
from harness_agent.web.models import WebResult
from harness_agent.web.safe_http import SafeHTTPError, check_url

logger = logging.getLogger("harness_agent.web")

# Fix Windows encoding before crawl4ai tries to log Unicode
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if _stream and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, DefaultMarkdownGenerator
    from crawl4ai.content_filter_strategy import PruningContentFilter

    CRAWL4AI_AVAILABLE = True
except ImportError:
    AsyncWebCrawler = None  # type: ignore
    BrowserConfig = None  # type: ignore
    CrawlerRunConfig = None  # type: ignore
    DefaultMarkdownGenerator = None  # type: ignore
    PruningContentFilter = None  # type: ignore
    CRAWL4AI_AVAILABLE = False


def _run_coro(coro: Any) -> Any:
    """Run an async coroutine safely, even inside an existing event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=_target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def _smart_wait_js(
    wait_initial_ms: int = 800,
    poll_interval_ms: int = 200,
    stable_checks: int = 3,
    max_checks: int = 15,
) -> str:
    """JavaScript snippet to wait for SPA DOM stability."""
    return (
        "() => new Promise(r => {"
        "  setTimeout(() => {"
        "    let last = document.body ? document.body.innerText.length : 0;"
        "    let stable = 0;"
        "    let checks = 0;"
        "    const interval = setInterval(() => {"
        f"      if (stable >= {stable_checks} || checks > {max_checks}) {{\n"
        "        clearInterval(interval); r(true);\n"
        "      }\n"
        "      last = now; checks++;\n"
        f"    }}, {poll_interval_ms});\n"
        f"  }}, {wait_initial_ms});\n"
        "})"
    )


def _check_final_url(
    entry_url: str, final_url: Optional[str], allow_private_hosts: Sequence[str]
) -> None:
    """Validate redirected destination URL against SSRF rules."""
    if not final_url or final_url == entry_url:
        return
    entry_host = urlparse(entry_url).hostname
    parsed_final = urlparse(final_url)
    if parsed_final.hostname == entry_host and parsed_final.scheme.lower() in ("http", "https"):
        return
    try:
        check_url(final_url, allow_private_hosts)
    except SafeHTTPError as exc:
        raise SafeHTTPError(
            f"browser navigation for {entry_url!r} ended at refused URL: {exc}"
        ) from exc


class Crawl4AIProvider:
    """Local headless browser crawler using open-source crawl4ai."""

    name: str = "crawl4ai"

    def __init__(
        self,
        headless: bool = True,
        page_timeout_ms: int = 30000,
        wait_initial_ms: int = 800,
        poll_interval_ms: int = 200,
        stable_checks: int = 3,
        max_checks: int = 15,
        fallback_to_builtin: bool = True,
    ) -> None:
        self.headless = headless
        self.page_timeout_ms = page_timeout_ms
        self.fallback_to_builtin = fallback_to_builtin
        self.builtin_provider = BuiltinProvider()

        self._wait_js = "js:" + _smart_wait_js(
            wait_initial_ms=wait_initial_ms,
            poll_interval_ms=poll_interval_ms,
            stable_checks=stable_checks,
            max_checks=max_checks,
        )

    def fetch(self, url: str, allow_private_hosts: Sequence[str] = ()) -> WebResult:
        """Fetch URL using local headless browser or fall back to BuiltinProvider."""
        check_url(url, allow_private_hosts)

        if not CRAWL4AI_AVAILABLE:
            if self.fallback_to_builtin:
                logger.info(
                    "crawl4ai is not installed. Falling back to built-in fast HTML crawler."
                )
                return self.builtin_provider.fetch(url, allow_private_hosts=allow_private_hosts)
            raise RuntimeError("crawl4ai is not installed and fallback_to_builtin=False")

        try:
            return _run_coro(self._fetch_async(url, allow_private_hosts))
        except Exception as exc:
            if self.fallback_to_builtin:
                logger.warning(
                    "crawl4ai headless execution failed (%s). Falling back to built-in crawler.",
                    exc,
                )
                return self.builtin_provider.fetch(url, allow_private_hosts=allow_private_hosts)
            raise

    async def _fetch_async(self, url: str, allow_private_hosts: Sequence[str]) -> WebResult:
        if AsyncWebCrawler is None or BrowserConfig is None or CrawlerRunConfig is None:
            raise RuntimeError("crawl4ai components are not available")

        browser_config = BrowserConfig(headless=self.headless, ignore_https_errors=False)
        md_generator = DefaultMarkdownGenerator(content_filter=PruningContentFilter())
        run_config = CrawlerRunConfig(
            simulate_user=True,
            page_timeout=self.page_timeout_ms,
            wait_for=self._wait_js,
            markdown_generator=md_generator,
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)
            if not getattr(result, "success", True):
                error_msg = getattr(result, "error_message", "Unknown crawl4ai error")
                raise RuntimeError(f"crawl4ai error: {error_msg}")

            landing_url = getattr(result, "redirected_url", None) or getattr(result, "url", url)
            _check_final_url(url, landing_url, allow_private_hosts)

            # Extract markdown: prefer fit_markdown over raw_markdown
            md = getattr(result, "markdown", None)
            content = ""
            if md and hasattr(md, "fit_markdown"):
                content = md.fit_markdown or md.raw_markdown or ""
            elif md and hasattr(md, "raw_markdown"):
                content = md.raw_markdown or ""
            elif isinstance(md, str):
                content = md

            metadata = getattr(result, "metadata", {}) or {}
            title = metadata.get("title", "")

            # If title is empty, attempt regex extraction from HTML
            raw_html = getattr(result, "html", "") or ""
            if not title and raw_html:
                m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
                if m:
                    title = m.group(1).strip()

            media_raw = getattr(result, "media", {}) or {}
            media = media_raw.get("images", []) if isinstance(media_raw, dict) else []

            links_raw = getattr(result, "links", {}) or {}
            links = []
            if isinstance(links_raw, dict):
                for link in links_raw.get("internal", []):
                    links.append({**link, "type": "internal"})
                for link in links_raw.get("external", []):
                    links.append({**link, "type": "external"})

            return WebResult(
                url=landing_url,
                title=title,
                content=content,
                raw_html=raw_html,
                fetched_at=datetime.now(timezone.utc),
                metadata=metadata,
                media=media,
                links=links,
            )

    def fetch_many(
        self, urls: Sequence[str], allow_private_hosts: Sequence[str] = ()
    ) -> List[WebResult]:
        """Fetch multiple URLs."""
        results: List[WebResult] = []
        for u in urls:
            try:
                results.append(self.fetch(u, allow_private_hosts=allow_private_hosts))
            except Exception as exc:
                logger.warning("failed to fetch %s: %s", u, exc)
        return results
