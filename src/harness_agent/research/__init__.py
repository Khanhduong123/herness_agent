"""Research subpackage for document ingestion, scholarly paper search,
claim extraction, and citation checking.
"""

from __future__ import annotations

from harness_agent.research.citecheck import (
    CiteCheckReport,
    check_report_citations,
    check_report_file,
    load_sources_from_dir,
    parse_numbered_citation_ids,
    parse_sources_section,
    split_sentences,
)
from harness_agent.research.claims import (
    CitationPair,
    Claim,
    extract_numbers,
    is_strong_claim,
    triage_citation,
)
from harness_agent.research.researcher import (
    detect_domain_role,
    extract_text_from_html,
    fetch_web_page,
    read_external_file,
    read_external_source,
    read_issue_tracker,
    read_pdf_document,
    scan_project_domain_boundaries,
)
from harness_agent.research.scholar import (
    PaperMetadata,
    extract_paper_blueprint,
    fetch_paper_fulltext,
    invert_openalex_abstract,
    normalize_title_key,
    parse_arxiv_atom,
    search_ai_papers,
    search_arxiv,
    search_openalex,
)

__all__ = [
    "CitationPair",
    "CiteCheckReport",
    "Claim",
    "PaperMetadata",
    "check_report_citations",
    "check_report_file",
    "detect_domain_role",
    "extract_numbers",
    "extract_paper_blueprint",
    "load_sources_from_dir",
    "parse_numbered_citation_ids",
    "parse_sources_section",
    "split_sentences",
    "extract_text_from_html",
    "fetch_paper_fulltext",
    "fetch_web_page",
    "invert_openalex_abstract",
    "is_strong_claim",
    "normalize_title_key",
    "parse_arxiv_atom",
    "read_external_file",
    "read_external_source",
    "read_issue_tracker",
    "read_pdf_document",
    "scan_project_domain_boundaries",
    "search_ai_papers",
    "search_arxiv",
    "search_openalex",
    "triage_citation",
]
