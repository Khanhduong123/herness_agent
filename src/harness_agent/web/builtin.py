"""Builtin web crawler and pure-Python HTML extractor.

Uses stdlib `html.parser.HTMLParser` (or beautifulsoup4 if installed) with SSRF-safe
HTTP fetching via `safe_http`. Strips boilerplate, navigations, scripts, and stylesheets,
converting headings, lists, code fences, and paragraphs into clean markdown.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from harness_agent.web.models import WebResult
from harness_agent.web.safe_http import safe_get


def _longest_backtick_run(text: str) -> int:
    return max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)


def _fence_for(code: str) -> str:
    """Return a backtick fence longer than any backtick run inside code."""
    return "`" * max(3, _longest_backtick_run(code) + 1)


def _fenced(code: str) -> str:
    """Wrap code block in a backtick fence."""
    fence = _fence_for(code)
    body = code.strip("\n")
    return f"\n{fence}\n{body}\n{fence}\n"


def _inline_code(text: str) -> str:
    """Wrap inline code in safe backticks."""
    if "`" in text:
        ticks = "`" * (_longest_backtick_run(text) + 1)
        return f"{ticks} {text} {ticks}"
    return f"`{text}`"


class _TextExtractor(HTMLParser):
    """Pure-Python standard library HTML to Markdown extractor."""

    def __init__(self, base_url: str = "") -> None:
        super().__init__()
        self.base_url = base_url
        self._segments: List[Tuple[str, str]] = []
        self._skip = False
        self._skip_depth = 0
        self._skip_tags = {
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside",
            "svg",
            "noscript",
            "iframe",
        }
        self.title = ""
        self._in_title = False
        self._in_pre = False
        self._pre_buf: List[str] = []
        self._in_inline_code = False
        self._current_href: Optional[str] = None
        self._link_buf: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        if tag_lower in self._skip_tags:
            self._skip = True
            self._skip_depth += 1
            return

        if self._skip:
            return

        if self._in_pre:
            if tag_lower == "br":
                self._pre_buf.append("\n")
            return

        if tag_lower == "title":
            self._in_title = True
            return

        if tag_lower == "pre":
            self._in_pre = True
            self._pre_buf = []
            return

        if tag_lower == "code":
            self._in_inline_code = True
            return

        if tag_lower == "a":
            href = attr_dict.get("href")
            if href and not href.startswith("javascript:") and not href.startswith("#"):
                self._current_href = urljoin(self.base_url, href) if self.base_url else href
                self._link_buf = []
            return

        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_lower[1])
            self._segments.append(("text", f"\n\n{'#' * level} "))
            return

        if tag_lower == "li":
            self._segments.append(("text", "\n* "))
            return

        if tag_lower in ("p", "div", "section", "article"):
            self._segments.append(("text", "\n\n"))
            return

        if tag_lower == "br":
            self._segments.append(("text", "\n"))

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._skip_tags:
            self._skip_depth -= 1
            if self._skip_depth <= 0:
                self._skip = False
                self._skip_depth = 0
            return

        if self._skip:
            return

        if tag_lower == "pre" and self._in_pre:
            self._in_pre = False
            code = "".join(self._pre_buf)
            self._pre_buf = []
            if code.strip():
                self._segments.append(("code", code))
            return

        if tag_lower == "title":
            self._in_title = False
            return

        if tag_lower == "code":
            self._in_inline_code = False
            return

        if tag_lower == "a" and self._current_href:
            link_text = "".join(self._link_buf).strip()
            href = self._current_href
            self._current_href = None
            self._link_buf = []
            if link_text:
                self._segments.append(("text", f"[{link_text}]({href})"))
            return

        if tag_lower in ("p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._segments.append(("text", "\n\n"))

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = (self.title + " " + data).strip()
            return

        if self._skip:
            return

        if self._in_pre:
            self._pre_buf.append(data)
            return

        if self._current_href is not None:
            self._link_buf.append(data)
            return

        if self._in_inline_code:
            clean = data.strip()
            if clean:
                self._segments.append(("text", f" {_inline_code(clean)} "))
            return

        self._segments.append(("text", data))

    def get_text(self) -> str:
        out: List[str] = []
        buf: List[str] = []

        def flush() -> None:
            raw = "".join(buf)
            lines = [line.strip() for line in raw.splitlines()]
            cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
            if cleaned:
                out.append(cleaned)
            buf.clear()

        for kind, text in self._segments:
            if kind == "text":
                buf.append(text)
            else:
                flush()
                out.append(_fenced(text).strip("\n"))
        flush()
        result = "\n\n".join(out)
        return re.sub(r"\n{3,}", "\n\n", result).strip()


class BuiltinProvider:
    """Built-in crawler using SSRF-safe HTTP fetching and HTML-to-markdown extraction."""

    name: str = "builtin"

    def __init__(self, max_bytes: int = 10 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes

    def fetch(self, url: str, allow_private_hosts: Sequence[str] = ()) -> WebResult:
        """Fetch URL safely and extract clean markdown content.

        Args:
            url: Target web page URL.
            allow_private_hosts: Hosts allowed despite private IP resolution.

        Returns:
            WebResult with extracted title, markdown content, and untrusted-source wrapper.
        """
        resp = safe_get(
            url,
            max_bytes=self.max_bytes,
            allow_private_hosts=allow_private_hosts,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} fetching {url}")

        return self.extract(resp.text, url=resp.url)

    def extract(self, html: str, url: str = "") -> WebResult:
        """Extract title and markdown text from HTML."""
        # Try bs4 if available, otherwise use pure stdlib parser
        try:
            from bs4 import BeautifulSoup, NavigableString

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "svg"]):
                tag.decompose()

            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            for pre in soup.find_all("pre"):
                code_text = pre.get_text()
                pre.clear()
                if code_text.strip():
                    pre.append(NavigableString(_fenced(code_text)))
            for code in soup.find_all("code"):
                code_text = code.get_text()
                code.clear()
                if code_text.strip():
                    pre_parents = code.find_parents("pre")
                    if not pre_parents:
                        code.append(NavigableString(f" {_inline_code(code_text.strip())} "))
            text = soup.get_text(separator="\n", strip=True)
            cleaned_text = re.sub(r"\n{3,}", "\n\n", text).strip()
            return WebResult(
                url=url,
                title=title,
                content=cleaned_text,
                raw_html=html,
            )
        except ImportError:
            pass

        # Pure stdlib HTMLParser fallback
        parser = _TextExtractor(base_url=url)
        parser.feed(html)
        return WebResult(
            url=url,
            title=parser.title,
            content=parser.get_text(),
            raw_html=html,
        )
