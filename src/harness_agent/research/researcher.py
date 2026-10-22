"""Researcher utilities for securely fetching and ingesting external data."""

from __future__ import annotations

import os
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from harness_agent.core.models import DOMAIN_PROFILES, AgentRole
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


def _normalize_relative_path(path: str | Path) -> str:
    """Normalize file path to POSIX style relative path for pattern matching."""
    raw = str(path).strip().replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    return raw.lstrip("/")


def _matches_pattern(normalized_path: str, pattern: str) -> bool:
    """Match a normalized path against a domain pattern."""
    pat = pattern.replace("\\", "/")
    if pat.endswith("/"):
        prefix = pat.lstrip("/")
        return normalized_path.startswith(prefix) or f"/{prefix}" in f"/{normalized_path}"
    if "*" in pat:
        import fnmatch

        filename = os.path.basename(normalized_path)
        return fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(normalized_path, pat)
    return normalized_path.endswith(pat) or pat == os.path.basename(normalized_path)


def detect_domain_role(file_paths: List[str]) -> AgentRole:
    """Analyze a list of targeted file paths and match against DOMAIN_PROFILES.

    Returns canonical AgentRole (DATABASE, BACKEND, FRONTEND, DEVOPS, AI_ML)
    or falls back to AgentRole.CODER if no specific match or ambiguous.
    """
    if not file_paths:
        return AgentRole.CODER

    role_counts: Dict[AgentRole, int] = {}
    for path in file_paths:
        norm = _normalize_relative_path(path)
        if not norm:
            continue
        matched_role: Optional[AgentRole] = None
        for role, patterns in DOMAIN_PROFILES.items():
            if any(_matches_pattern(norm, pat) for pat in patterns):
                matched_role = role
                break
        if matched_role is not None:
            role_counts[matched_role] = role_counts.get(matched_role, 0) + 1

    if not role_counts:
        return AgentRole.CODER

    # Pick the role with the highest score; fallback to CODER if tie/ambiguous
    sorted_roles = sorted(role_counts.items(), key=lambda item: item[1], reverse=True)
    top_role, top_count = sorted_roles[0]
    if len(sorted_roles) > 1 and sorted_roles[1][1] == top_count:
        return AgentRole.CODER
    return top_role


def scan_project_domain_boundaries(root_dir: str | Path) -> Dict[AgentRole, List[str]]:
    """Scan project directory structure and group discovered paths by canonical domain role."""
    base_dir = Path(root_dir).resolve()
    boundaries: Dict[AgentRole, List[str]] = {role: [] for role in DOMAIN_PROFILES}

    if not base_dir.exists() or not base_dir.is_dir():
        return boundaries

    ignore_dirs = {
        ".git",
        ".worktrees",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
    }

    discovered_files: List[str] = []
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            full_path = Path(root) / f
            try:
                rel_path = full_path.relative_to(base_dir).as_posix()
            except ValueError:
                rel_path = str(full_path).replace("\\", "/")
            discovered_files.append(rel_path)

    for rel_path in discovered_files:
        for role, patterns in DOMAIN_PROFILES.items():
            if any(_matches_pattern(rel_path, pat) for pat in patterns):
                boundaries[role].append(rel_path)
                break

    return boundaries
