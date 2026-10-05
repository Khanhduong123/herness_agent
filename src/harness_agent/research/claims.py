"""Claim extraction, numeric alignment, and factual verification gate.

Extracts factual assertions, statistical markers, currencies, and quantitative changes
from sentences and verifies alignment against cited source texts.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

_STRONG_MARKERS = (
    "%",
    "$",
    "€",
    "£",
    "billion",
    "million",
    "trillion",
    "thousand",
    "increase",
    "decrease",
    "grew",
    "fell",
    "rose",
    "dropped",
    "growth",
    "reduction",
)

_NUMBER_RE = re.compile(r"(?:\$|€|£)?\d+(?:,\d{3})*(?:\.\d+)?%?")
_CITE_STRIP_RE = re.compile(r"\[\d+(?:\s*[-–,]\s*\d+)*\]|\[\[[^\]]+\]\]")


def normalize_text(text: str) -> str:
    """Normalize text by collapsing whitespace and lowercasing."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def strip_citations(text: str) -> str:
    """Remove inline citation markers ([1], [1-3], [[key]]) from text."""
    return _CITE_STRIP_RE.sub("", text)


def extract_numbers(text: str) -> List[str]:
    """Extract numeric tokens, percentages, and currencies from text."""
    clean_text = strip_citations(text)
    return [m.group(0) for m in _NUMBER_RE.finditer(clean_text)]


def is_strong_claim(text: str) -> bool:
    """Check if text contains numeric data or quantitative change markers."""
    clean = strip_citations(text)
    lower = clean.lower()
    if bool(_NUMBER_RE.search(clean)):
        return True
    return any(marker in lower for marker in _STRONG_MARKERS)


def find_word_overlap_shingle(
    sentence: str,
    source_text: str,
    shingle_len: int = 5,
) -> bool:
    """Check if any consecutive N-word shingle from sentence appears in source_text."""
    norm_s = normalize_text(strip_citations(sentence))
    norm_src = normalize_text(source_text)
    # Strip punctuation from sentence words
    words = [re.sub(r"[^\w-]", "", w) for w in norm_s.split()]
    words = [w for w in words if w]

    if len(words) < shingle_len:
        return " ".join(words) in norm_src if words else False

    for i in range(len(words) - shingle_len + 1):
        shingle = " ".join(words[i : i + shingle_len])
        if shingle and shingle in norm_src:
            return True
    return False


class CitationPair(BaseModel):
    """Binding between a sentence and a cited source with verification status."""

    sentence: str
    source_id: Optional[str] = None
    numbers: List[str] = Field(default_factory=list)
    strong: bool = False
    verdict: str = "unknown"
    details: str = ""


class Claim(BaseModel):
    """An extracted factual or numeric assertion."""

    claim_text: str
    numbers: List[str] = Field(default_factory=list)
    strong: bool = False
    source_id: Optional[str] = None
    verdict: str = "unknown"
    details: str = ""


def triage_citation(
    sentence: str,
    cited_text: Optional[str],
    all_sources: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    """Triage citation claim against cited text and global sources corpus.

    Verdicts:
        - supported: Numbers and long phrasing match cited source.
        - partially-supported: Partial entity/phrase match but numbers differ
          or context is incomplete.
        - unsupported: Claim assertions do not exist in cited source.
        - wrong-source: Claim matches another source in the corpus instead
          of cited source.
        - dangling: Cited source is missing from corpus.

    Returns:
        (verdict, details) tuple.
    """
    if cited_text is None:
        return "dangling", "Referenced source was not found in sources corpus"

    nums = extract_numbers(sentence)
    clean_nums = [n.replace(",", "").replace("$", "").replace("%", "") for n in nums]
    norm_source = normalize_text(cited_text)

    # Check number matching
    all_nums_match = bool(clean_nums) and all(
        cn in norm_source or n.lower() in norm_source for cn, n in zip(clean_nums, nums)
    )
    any_num_match = bool(clean_nums) and any(
        cn in norm_source or n.lower() in norm_source for cn, n in zip(clean_nums, nums)
    )

    exact_5_overlap = find_word_overlap_shingle(sentence, cited_text, shingle_len=5)

    # 1. Full pass: verbatim 5-token overlap AND numbers match (or no numbers)
    if exact_5_overlap:
        if not clean_nums or all_nums_match:
            return "supported", "Numbers and verbatim text span confirmed in cited source"

    if (
        clean_nums
        and all_nums_match
        and find_word_overlap_shingle(sentence, cited_text, shingle_len=3)
    ):
        return "supported", "All numerical assertions and context match cited source"

    # 2. Check if statement belongs to a different source in corpus (wrong-source)
    if all_sources:
        for other_id, other_text in all_sources.items():
            norm_other = normalize_text(other_text)
            other_overlap = find_word_overlap_shingle(sentence, other_text, shingle_len=5)
            other_nums_match = bool(clean_nums) and all(
                cn in norm_other or n.lower() in norm_other for cn, n in zip(clean_nums, nums)
            )
            if (other_overlap and (not clean_nums or other_nums_match)) or (
                clean_nums
                and other_nums_match
                and find_word_overlap_shingle(sentence, other_text, shingle_len=3)
            ):
                return "wrong-source", f"Claim matches source '{other_id}' rather than cited source"

    # 3. Partial pass: partial overlap or some numbers match
    partial_overlap = find_word_overlap_shingle(sentence, cited_text, shingle_len=3)
    if partial_overlap or any_num_match:
        if clean_nums and not all_nums_match:
            return (
                "partially-supported",
                "Context matches source but numerical values differ or are unverified",
            )
        return (
            "partially-supported",
            "Partial textual overlap with source, but lacking full verbatim confirmation",
        )

    # 4. Hard refusal
    return "unsupported", "Claim assertions and numbers not found in cited source"


def extract_claims(text: str) -> List[Claim]:
    """Extract individual claims from prose text."""
    claims: List[Claim] = []
    sentence_delimiters = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|\n+")
    for sent in sentence_delimiters.split(text):
        s = sent.strip()
        if not s:
            continue
        nums = extract_numbers(s)
        strong = is_strong_claim(s)
        claims.append(
            Claim(
                claim_text=s,
                numbers=nums,
                strong=strong,
            )
        )
    return claims
