"""Unit tests for scholarly search and paper ingestion engine."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from harness_agent.cli import main
from harness_agent.scholar import (
    PaperMetadata,
    extract_paper_blueprint,
    invert_openalex_abstract,
    normalize_title_key,
    parse_arxiv_atom,
    search_ai_papers,
)

SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Search Results</title>
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <published>2023-01-01T12:00:00Z</published>
    <title>Deep Research Harness: Autonomous Agent Evaluation</title>
    <summary>Automated evaluation harness for large language models.</summary>
    <author>
      <name>Alice Smith</name>
    </author>
    <author>
      <name>Bob Jones</name>
    </author>
    <link href="http://arxiv.org/abs/2301.00001v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2301.00001v1.pdf" rel="related"/>
  </entry>
</feed>
"""


def test_invert_openalex_abstract():
    """Verify inverted index reconstructs into coherent abstract."""
    # Test valid index
    inverted = {
        "This": [0],
        "is": [1],
        "a": [2],
        "deep": [3],
        "research": [4],
        "paper.": [5],
    }
    reconstructed = invert_openalex_abstract(inverted)
    assert reconstructed == "This is a deep research paper."

    # Test empty or None
    assert invert_openalex_abstract(None) is None
    assert invert_openalex_abstract({}) is None


def test_parse_arxiv_atom():
    """Verify arXiv Atom XML parses into PaperMetadata."""
    papers = parse_arxiv_atom(SAMPLE_ARXIV_XML)
    assert len(papers) == 1

    paper = papers[0]
    assert paper.title == "Deep Research Harness: Autonomous Agent Evaluation"
    assert paper.arxiv_id == "2301.00001v1"
    assert paper.year == 2023
    assert paper.authors == ["Alice Smith", "Bob Jones"]
    assert "automated evaluation harness" in (paper.abstract or "").lower()
    assert paper.pdf_url == "http://arxiv.org/pdf/2301.00001v1.pdf"
    assert paper.provider == "arxiv"


def test_normalize_title_key():
    """Verify title normalization for deduplication."""
    t1 = "Attention Is All You Need!"
    t2 = "attention is all you need"
    assert normalize_title_key(t1) == normalize_title_key(t2)
    assert normalize_title_key(t1) == "attentionisallyouneed"


def test_extract_paper_blueprint():
    """Verify heuristic extraction of architectures, loss functions, and hyperparameters."""
    sample_text = """
    We propose a novel Transformer block using Multi-Head Attention and SwiGLU activation.
    The model is optimized using Cross-Entropy loss with learning rate 3e-4 and batch size 64.
    Evaluations on MMLU and GSM8K show significant improvements over prior baselines.
    """
    blueprint = extract_paper_blueprint(sample_text)

    # Architecture components
    archs = [a.lower() for a in blueprint["model_architecture"]]
    assert any("transformer" in a for a in archs)
    assert any("attention" in a for a in archs)
    assert any("swiglu" in a for a in archs)

    # Loss functions
    losses = [loss.lower() for loss in blueprint["loss_functions"]]
    assert any("cross-entropy" in loss_item for loss_item in losses)

    # Hyperparameters
    assert blueprint["hyperparameters"].get("learning_rate") == "3e-4"
    assert blueprint["hyperparameters"].get("batch_size") == 64

    # Benchmarks
    assert "MMLU" in blueprint["benchmarks"]
    assert "GSM8K" in blueprint["benchmarks"]


def test_search_ai_papers_deduplication():
    """Verify deduplication across search providers."""
    mock_arxiv_papers = [
        PaperMetadata(
            title="Transformer Scaling Laws",
            authors=["John Doe"],
            year=2022,
            arxiv_id="2201.12345",
            doi="10.1000/182",
            provider="arxiv",
        )
    ]
    mock_openalex_papers = [
        PaperMetadata(
            title="Transformer Scaling Laws",
            authors=["John Doe", "Jane Doe"],
            year=2022,
            doi="10.1000/182",
            citation_count=150,
            provider="openalex",
        ),
        PaperMetadata(
            title="Unique Paper B",
            authors=["Alice"],
            year=2024,
            citation_count=10,
            provider="openalex",
        ),
    ]

    with patch("harness_agent.scholar.search_arxiv", return_value=mock_arxiv_papers):
        with patch("harness_agent.scholar.search_openalex", return_value=mock_openalex_papers):
            res = search_ai_papers("scaling laws", limit=5)
            assert res.total_found == 2
            titles = [p.title for p in res.papers]
            assert titles.count("Transformer Scaling Laws") == 1
            assert "Unique Paper B" in titles


def test_cli_scholar_search():
    """Verify scholar-search CLI command execution."""
    mock_papers = [
        PaperMetadata(
            title="Test AI Paper",
            authors=["Lead Author"],
            year=2024,
            arxiv_id="2401.99999",
            abstract="Brief abstract of the test paper.",
            citation_count=42,
            pdf_url="https://arxiv.org/pdf/2401.99999.pdf",
            provider="arxiv",
        )
    ]

    runner = CliRunner()
    with patch("harness_agent.scholar.search_arxiv", return_value=mock_papers):
        with patch("harness_agent.scholar.search_openalex", return_value=[]):
            # Test text format
            result = runner.invoke(main, ["scholar-search", "test query", "--limit", "2"])
            assert result.exit_code == 0
            assert "Test AI Paper" in result.output
            assert "Lead Author" in result.output
            assert "arXiv:2401.99999" in result.output

            # Test JSON format
            json_result = runner.invoke(main, ["scholar-search", "test query", "--json"])
            assert json_result.exit_code == 0
            data = json.loads(json_result.output)
            assert data["total_found"] == 1
            assert data["papers"][0]["title"] == "Test AI Paper"
