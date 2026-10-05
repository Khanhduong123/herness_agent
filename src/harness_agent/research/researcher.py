"""Researcher utilities for securely fetching and ingesting external data."""

from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from typing import Optional, Tuple

from harness_agent.core.security import wrap_untrusted_content


class HTMLTextExtractor(HTMLParser):
    """Extract readable text from HTML content, discarding scripts and styling."""

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "noscript", "nav", "footer", "header"}
        self._title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._skip_tags:
            self._skip = True
            return
        if tag_lower == "title":
            self._in_title = True
            return
        if tag_lower in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._skip_tags:
            self._skip = False
            return
        if tag_lower == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title = data.strip()
        if self._skip:
            return
        self._pieces.append(data)

    def get_clean_text(self) -> Tuple[str, str]:
        """Return (title, cleaned_text)."""
        raw = "".join(self._pieces)
        lines = [line.strip() for line in raw.splitlines()]
        cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        return self._title, cleaned


def extract_text_from_html(html: str) -> Tuple[str, str]:
    """Parse HTML and extract page title and clean body text."""
    extractor = HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_clean_text()


def fetch_web_page(
    url: str,
    html: Optional[str] = None,
    timeout: int = 15,
) -> str:
    """Fetch an external web page, extract body text, and enclose in untrusted-source tags.

    Args:
        url: The web page URL.
        html: Optional raw HTML string (used for testing or mock responses).
        timeout: Network request timeout in seconds.

    Returns:
        Securely wrapped prompt string with security warnings and delimiters.
    """
    raw_html = html
    if raw_html is None:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "HarnessAgent-Researcher/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            raw_html = resp.read().decode(charset, errors="replace")

    title, text_content = extract_text_from_html(raw_html)
    full_content = f"Title: {title}\n\n{text_content}" if title else text_content
    return wrap_untrusted_content(full_content, source_type="web", source_id=url)


def read_pdf_document(
    path_or_url: str,
    raw_text: Optional[str] = None,
) -> str:
    """Read external PDF text and enclose it in untrusted-source delimiters.

    Args:
        path_or_url: Local path or URL of the PDF document.
        raw_text: Extracted text if already parsed, or test mock content.

    Returns:
        Securely wrapped prompt string.
    """
    content = raw_text if raw_text is not None else f"(Extracted PDF content from {path_or_url})"
    return wrap_untrusted_content(content, source_type="pdf", source_id=path_or_url)


def read_issue_tracker(
    issue_id: str,
    body: str,
    title: Optional[str] = None,
) -> str:
    """Read an external issue/ticket description and enclose it in untrusted-source delimiters.

    Args:
        issue_id: Issue key, URL, or identifier (e.g. 'GH-102', 'JIRA-404').
        body: Raw description/body of the issue.
        title: Optional title of the issue.

    Returns:
        Securely wrapped prompt string.
    """
    content = f"Issue Title: {title}\n\n{body}" if title else body
    return wrap_untrusted_content(content, source_type="issue", source_id=issue_id)


def read_external_file(
    file_path: str,
    content: Optional[str] = None,
) -> str:
    """Read an external file from disk and enclose it in untrusted-source delimiters.

    Args:
        file_path: Path to the external file.
        content: Optional content override for testing.

    Returns:
        Securely wrapped prompt string.
    """
    if content is None:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            file_content = f.read()
    else:
        file_content = content

    return wrap_untrusted_content(file_content, source_type="file", source_id=file_path)


def read_external_source(
    source_type: str,
    content: str,
    source_id: Optional[str] = None,
) -> str:
    """Generic wrapper for any external text read into the agent's context."""
    return wrap_untrusted_content(content, source_type=source_type, source_id=source_id)
