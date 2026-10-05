"""Scholarly search and paper ingestion engine for AI and machine learning research."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from harness_agent.core.security import wrap_untrusted_content

logger = logging.getLogger(__name__)

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
ARXIV_QUERY_URL = "https://export.arxiv.org/api/query"


class PaperMetadata(BaseModel):
    """Normalized metadata for a research paper."""

    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    abstract: Optional[str] = None
    citation_count: Optional[int] = None
    pdf_url: Optional[str] = None
    venue: Optional[str] = None
    provider: str = "unknown"
    landing_url: Optional[str] = None


class PaperSearchResult(BaseModel):
    """Aggregated search result across multiple providers."""

    query: str
    total_found: int
    papers: List[PaperMetadata] = Field(default_factory=list)


def invert_openalex_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> Optional[str]:
    """Rebuild abstract prose from OpenAlex's ``{word: [positions]}`` inverted map.

    OpenAlex ships inverted indices for licensing reasons. This function
    reconstructs the original text by ordering words by position.
    """
    if not isinstance(inverted_index, dict) or not inverted_index:
        return None

    words_at_pos: List[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if isinstance(positions, list):
            for pos in positions:
                if isinstance(pos, int):
                    words_at_pos.append((pos, str(word)))

    if not words_at_pos:
        return None

    words_at_pos.sort(key=lambda item: item[0])
    return " ".join(word for _, word in words_at_pos)


def parse_arxiv_atom(xml_content: str) -> List[PaperMetadata]:
    """Parse arXiv Atom XML response into structured PaperMetadata instances."""
    papers: List[PaperMetadata] = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as err:
        logger.warning("Failed to parse arXiv Atom XML: %s", err)
        return papers

    for entry in root.findall("atom:entry", ns):
        title_elem = entry.find("atom:title", ns)
        summary_elem = entry.find("atom:summary", ns)
        id_elem = entry.find("atom:id", ns)
        published_elem = entry.find("atom:published", ns)

        raw_title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
        title = re.sub(r"\s+", " ", raw_title)
        if not title:
            continue

        raw_abstract = (
            summary_elem.text.strip() if summary_elem is not None and summary_elem.text else None
        )
        abstract = re.sub(r"\s+", " ", raw_abstract) if raw_abstract else None

        authors: List[str] = []
        for author in entry.findall("atom:author", ns):
            name_elem = author.find("atom:name", ns)
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())

        landing_url = id_elem.text.strip() if id_elem is not None and id_elem.text else None
        arxiv_id = None
        if landing_url:
            match = re.search(r"abs/([0-9]+\.[0-9]+(?:v[0-9]+)?)", landing_url)
            if match:
                arxiv_id = match.group(1)

        pdf_url = None
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href")
                break
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        year = None
        if published_elem is not None and published_elem.text:
            match_yr = re.search(r"\b(19\d\d|20\d\d)\b", published_elem.text)
            if match_yr:
                year = int(match_yr.group(1))

        papers.append(
            PaperMetadata(
                title=title,
                authors=authors,
                year=year,
                arxiv_id=arxiv_id,
                abstract=abstract,
                pdf_url=pdf_url,
                landing_url=landing_url,
                provider="arxiv",
            )
        )

    return papers


def search_openalex(query: str, limit: int = 5, timeout: int = 15) -> List[PaperMetadata]:
    """Search OpenAlex API for research papers matching query."""
    params = {
        "search": query,
        "per-page": min(max(1, limit), 25),
    }
    url = f"{OPENALEX_WORKS_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "HarnessAgent-Scholar/1.0 (mailto:scholar@harness-agent.dev)"},
    )

    papers: List[PaperMetadata] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("OpenAlex search failed: %s", exc)
        return papers

    results = data.get("results", [])
    for item in results:
        title = item.get("title")
        if not title:
            continue

        authors: List[str] = []
        for authorship in item.get("authorships", []):
            author_obj = authorship.get("author", {})
            name = author_obj.get("display_name")
            if name:
                authors.append(name)

        doi_raw = item.get("doi")
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else None

        abstract = invert_openalex_abstract(item.get("abstract_inverted_index"))

        primary_loc = item.get("primary_location") or {}
        pdf_url = primary_loc.get("pdf_url")
        landing_url = primary_loc.get("landing_page_url") or doi_raw

        source_dict = primary_loc.get("source") or {}
        venue = source_dict.get("display_name")

        papers.append(
            PaperMetadata(
                title=title.strip(),
                authors=authors,
                year=item.get("publication_year"),
                doi=doi,
                abstract=abstract,
                citation_count=item.get("cited_by_count"),
                pdf_url=pdf_url,
                venue=venue,
                landing_url=landing_url,
                provider="openalex",
            )
        )

    return papers


def search_arxiv(query: str, limit: int = 5, timeout: int = 15) -> List[PaperMetadata]:
    """Search arXiv API for preprints matching query."""
    clean_query = re.sub(r"[^a-zA-Z0-9\s_-]", "", query).strip()
    params = {
        "search_query": f"all:{clean_query}",
        "start": 0,
        "max_results": min(max(1, limit), 25),
    }
    url = f"{ARXIV_QUERY_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "HarnessAgent-Scholar/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml_data = resp.read().decode("utf-8", errors="replace")
        return parse_arxiv_atom(xml_data)
    except Exception as exc:
        logger.warning("arXiv search failed: %s", exc)
        return []


def normalize_title_key(title: str) -> str:
    """Normalize paper title for deduplication."""
    return re.sub(r"[^a-z0-9]", "", title.lower())


def search_ai_papers(
    query: str,
    limit: int = 5,
    providers: Optional[List[str]] = None,
    timeout: int = 15,
) -> PaperSearchResult:
    """Aggregated, deduplicated scholarly search across arXiv and OpenAlex."""
    target_providers = providers or ["arxiv", "openalex"]
    all_papers: List[PaperMetadata] = []

    if "arxiv" in target_providers:
        all_papers.extend(search_arxiv(query=query, limit=limit, timeout=timeout))

    if "openalex" in target_providers:
        all_papers.extend(search_openalex(query=query, limit=limit, timeout=timeout))

    # Deduplicate by DOI, arXiv ID, or normalized title
    seen_keys: set[str] = set()
    deduped: List[PaperMetadata] = []

    for paper in all_papers:
        key = None
        if paper.doi:
            key = f"doi:{paper.doi.lower()}"
        elif paper.arxiv_id:
            key = f"arxiv:{paper.arxiv_id.lower()}"
        elif paper.title:
            key = f"title:{normalize_title_key(paper.title)}"

        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        deduped.append(paper)

    # Sort primarily by citation count if available, then by recency (year)
    deduped.sort(
        key=lambda p: (p.citation_count or 0, p.year or 0),
        reverse=True,
    )

    final_papers = deduped[:limit]
    return PaperSearchResult(
        query=query,
        total_found=len(deduped),
        papers=final_papers,
    )


def fetch_paper_fulltext(url_or_doi: str, timeout: int = 20) -> str:
    """Fetch text from open access URL or landing page, enclosed in security wrapper."""
    target_url = url_or_doi
    if not target_url.startswith("http://") and not target_url.startswith("https://"):
        target_url = f"https://doi.org/{url_or_doi}"

    req = urllib.request.Request(
        target_url,
        headers={"User-Agent": "HarnessAgent-Scholar/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read().decode(charset, errors="replace")
    except Exception as exc:
        raw = f"(Failed to fetch full-text from {target_url}: {exc})"

    return wrap_untrusted_content(raw, source_type="scholarly_paper", source_id=url_or_doi)


def extract_paper_blueprint(paper_text: str) -> Dict[str, Any]:
    """Heuristic extraction of architecture layers, equations, and benchmarks from paper text."""
    blueprint: Dict[str, Any] = {
        "model_architecture": [],
        "loss_functions": [],
        "hyperparameters": {},
        "benchmarks": [],
    }

    # Extract model architecture layers / components
    arch_patterns = [
        (
            r"(?:transformer|attention|encoder|decoder|mlp|convolutional|residual"
            r"|feedforward|lstm)\s+(?:layer|block|module|head)"
        ),
        r"(?:multi-head\s+attention|self-attention|cross-attention)",
        r"(?:rmsnorm|layernorm|swiglu|gelu|relu)\s+(?:activation|normalization)?",
    ]
    for pattern in arch_patterns:
        matches = re.findall(pattern, paper_text, re.IGNORECASE)
        for m in matches:
            cleaned = m.strip().title()
            if cleaned not in blueprint["model_architecture"]:
                blueprint["model_architecture"].append(cleaned)

    # Extract equations or loss function mentions
    loss_patterns = [
        (
            r"(?:cross-entropy|mse|kl-divergence|contrastive|info-nce|ppo|dpo|triplet)"
            r"\s+(?:loss|objective)"
        ),
        r"(?:regularization|weight\s+decay|l2\s+penalty)",
    ]
    for pattern in loss_patterns:
        matches = re.findall(pattern, paper_text, re.IGNORECASE)
        for m in matches:
            cleaned = m.strip().title()
            if cleaned not in blueprint["loss_functions"]:
                blueprint["loss_functions"].append(cleaned)

    # Extract standard hyperparameters
    lr_match = re.search(
        r"(?:learning\s+rate|lr)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?(?:e-[0-9]+)?)",
        paper_text,
        re.IGNORECASE,
    )
    if lr_match:
        blueprint["hyperparameters"]["learning_rate"] = lr_match.group(1)

    batch_match = re.search(r"(?:batch\s+size)\s*[:=]?\s*([0-9]+)", paper_text, re.IGNORECASE)
    if batch_match:
        blueprint["hyperparameters"]["batch_size"] = int(batch_match.group(1))

    # Extract benchmark names
    bench_patterns = [
        r"(?:glue|superglue|mmlu|gsm8k|humaneval|swe-bench|arc|hellaswag|truthfulqa)",
    ]
    for pattern in bench_patterns:
        matches = re.findall(pattern, paper_text, re.IGNORECASE)
        for m in matches:
            cleaned = m.strip().upper()
            if cleaned not in blueprint["benchmarks"]:
                blueprint["benchmarks"].append(cleaned)

    return blueprint
