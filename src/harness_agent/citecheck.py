"""Citation extraction and report verification gate.

Parses inline numbered references ([1], [2, 3], [1-3]) and wikilinks ([[source-id]]),
resolves them against sources/bibliography sections and source files, and triages
every assertion into supported, partially-supported, unsupported, or wrong-source.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from pydantic import BaseModel, Field

from harness_agent.claims import CitationPair, extract_numbers, is_strong_claim, triage_citation

_ABBREVIATIONS = (
    "et al.",
    "dr.",
    "mr.",
    "mrs.",
    "ms.",
    "prof.",
    "e.g.",
    "i.e.",
    "fig.",
    "vs.",
    "inc.",
    "corp.",
    "ph.d.",
    "approx.",
)

_CITE_BRACKET_RE = re.compile(r"\[(\d{1,3}(?:\s*[-–,]\s*\d{1,3})*)\]")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_SOURCES_ENTRY_RE = re.compile(r"^\[(\d{1,3})\]\s+(.+)$")


def split_sentences(text: str) -> List[str]:
    """Split text into sentences while respecting common abbreviations."""
    masked = text
    saved: Dict[str, str] = {}
    counter = 0

    for abbr in _ABBREVIATIONS:
        pattern = re.compile(r"\b" + re.escape(abbr), re.IGNORECASE)

        def _repl(m: re.Match) -> str:
            nonlocal counter
            key = f"XAbbrToken{counter}X"
            saved[key] = m.group(0)
            counter += 1
            return key

        masked = pattern.sub(_repl, masked)

    split_pattern = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u4e00-\u9fff])|\n{2,}")
    raw_sentences = split_pattern.split(masked)

    sentences: List[str] = []
    for s in raw_sentences:
        clean = s.strip()
        if not clean:
            continue
        for key, orig in saved.items():
            clean = clean.replace(key, orig)
        clean = re.sub(r"\s+", " ", clean)
        sentences.append(clean)
    return sentences


def parse_numbered_citation_ids(cite_str: str) -> List[str]:
    """Parse citation indices including comma lists and hyphen ranges.

    Examples:
        '1' -> ['1']
        '2, 3' -> ['2', '3']
        '1-3' -> ['1', '2', '3']
        '1, 4-6' -> ['1', '4', '5', '6']
    """
    results: List[str] = []
    parts = re.split(r"\s*,\s*", cite_str)
    for part in parts:
        if not part:
            continue
        range_match = re.split(r"\s*[-–]\s*", part)
        if len(range_match) == 2 and range_match[0].isdigit() and range_match[1].isdigit():
            start, end = int(range_match[0]), int(range_match[1])
            for num in range(start, end + 1):
                results.append(str(num))
        elif part.isdigit():
            results.append(part)
    return results


def parse_sources_section(report_text: str) -> Dict[str, str]:
    """Parse '## Sources' or '## References' section to map index [N] to URL or identifier."""
    mapping: Dict[str, str] = {}
    in_sources = False
    for raw_line in report_text.splitlines():
        line = raw_line.strip()
        if re.match(r"^##\s+(?:Sources|References)\b", line, re.IGNORECASE):
            in_sources = True
            continue
        if in_sources and line.startswith("## "):
            break
        if not in_sources:
            continue
        m = _SOURCES_ENTRY_RE.match(line)
        if not m:
            continue
        num, rest = m.group(1), m.group(2).strip()
        url_m = re.search(r"https?://\S+", rest)
        if url_m:
            mapping[num] = url_m.group(0).rstrip(".,)")
        else:
            mapping[num] = rest
    return mapping


def load_sources_from_dir(sources_dir: Union[str, Path]) -> Dict[str, str]:
    """Load all source files from a directory into a dictionary keyed by name and stem."""
    path = Path(sources_dir)
    if not path.is_dir():
        return {}

    sources: Dict[str, str] = {}
    for file_path in path.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in (".md", ".txt", ".html", ".json"):
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                sources[file_path.name] = content
                sources[file_path.stem] = content
                # Index by any URL found in source frontmatter or header
                for url_match in re.finditer(r"https?://\S+", content[:1000]):
                    url = url_match.group(0).rstrip(".,)\"'>")
                    sources[url] = content
            except Exception:
                pass
    return sources


class CiteCheckReport(BaseModel):
    """Aggregated citation verification audit report."""

    report_file: str = ""
    total_sentences: int = 0
    total_citations: int = 0
    supported: int = 0
    partially_supported: int = 0
    unsupported: int = 0
    wrong_source: int = 0
    dangling: int = 0
    pairs: List[CitationPair] = Field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_citations == 0:
            return 100.0
        return round((self.supported / self.total_citations) * 100.0, 1)


def check_report_citations(
    report_text: str,
    sources: Dict[str, str],
    report_file: str = "",
) -> CiteCheckReport:
    """Analyze all sentences and citation markers in a report against sources."""
    sources_map = parse_sources_section(report_text)

    # Strip the sources section from the analyzed body
    body = re.split(r"^##\s+(?:Sources|References)\b", report_text, maxsplit=1, flags=re.M | re.I)[
        0
    ]
    sentences = split_sentences(body)

    pairs: List[CitationPair] = []
    supported_cnt = 0
    partially_supported_cnt = 0
    unsupported_cnt = 0
    wrong_source_cnt = 0
    dangling_cnt = 0

    for sentence in sentences:
        cited_keys: Set[str] = set()

        # Extract [N] or [N, M] or [N-M] citations
        for m in _CITE_BRACKET_RE.finditer(sentence):
            for num in parse_numbered_citation_ids(m.group(1)):
                resolved = sources_map.get(num, num)
                cited_keys.add(resolved)

        # Extract [[source-key]] wikilinks
        for m in _WIKILINK_RE.finditer(sentence):
            cited_keys.add(m.group(1).strip())

        nums = extract_numbers(sentence)
        strong = is_strong_claim(sentence)

        for source_key in cited_keys:
            # Resolve source content from corpus
            source_content = sources.get(source_key)
            if source_content is None:
                # Try finding by partial stem or url match
                for k, v in sources.items():
                    if source_key in k or k in source_key:
                        source_content = v
                        break

            verdict, details = triage_citation(
                sentence=sentence,
                cited_text=source_content,
                all_sources=sources,
            )

            if verdict == "supported":
                supported_cnt += 1
            elif verdict == "partially-supported":
                partially_supported_cnt += 1
            elif verdict == "unsupported":
                unsupported_cnt += 1
            elif verdict == "wrong-source":
                wrong_source_cnt += 1
            elif verdict == "dangling":
                dangling_cnt += 1

            pairs.append(
                CitationPair(
                    sentence=sentence,
                    source_id=source_key,
                    numbers=nums,
                    strong=strong,
                    verdict=verdict,
                    details=details,
                )
            )

    return CiteCheckReport(
        report_file=report_file,
        total_sentences=len(sentences),
        total_citations=len(pairs),
        supported=supported_cnt,
        partially_supported=partially_supported_cnt,
        unsupported=unsupported_cnt,
        wrong_source=wrong_source_cnt,
        dangling=dangling_cnt,
        pairs=pairs,
    )


def check_report_file(
    report_path: Union[str, Path],
    sources_dir: Optional[Union[str, Path]] = None,
) -> CiteCheckReport:
    """Run citation audit on a report file on disk."""
    path = Path(report_path)
    if not path.is_file():
        raise FileNotFoundError(f"Report file not found: {report_path}")

    report_text = path.read_text(encoding="utf-8-sig")
    sources: Dict[str, str] = {}
    if sources_dir:
        sources = load_sources_from_dir(sources_dir)

    return check_report_citations(report_text, sources=sources, report_file=str(path))
