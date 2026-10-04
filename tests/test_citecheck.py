"""Unit tests for sentence splitting, citation extraction, claim triage, and cite-check audit."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from harness_agent.citecheck import (
    check_report_file,
    parse_numbered_citation_ids,
    parse_sources_section,
    split_sentences,
)
from harness_agent.claims import triage_citation
from harness_agent.cli import main


def test_split_sentences_preserves_abbreviations() -> None:
    text = (
        "According to Smith et al., deep learning models achieve 95% accuracy. "
        "Dr. Jones and Prof. Miller agreed with the findings. "
        "For e.g., the benchmark demonstrates rapid convergence! "
        "Does this hold in practice? Further studies confirm it."
    )
    sentences = split_sentences(text)
    assert len(sentences) == 5
    assert "Smith et al." in sentences[0]
    assert "Dr. Jones and Prof. Miller agreed" in sentences[1]
    assert "e.g." in sentences[2]
    assert sentences[3] == "Does this hold in practice?"
    assert sentences[4] == "Further studies confirm it."


def test_parse_numbered_citation_ids() -> None:
    assert parse_numbered_citation_ids("1") == ["1"]
    assert parse_numbered_citation_ids("2, 3") == ["2", "3"]
    assert parse_numbered_citation_ids("1-3") == ["1", "2", "3"]
    assert parse_numbered_citation_ids("1, 4-6, 9") == ["1", "4", "5", "6", "9"]


def test_parse_sources_section() -> None:
    doc = """
    # Analysis Report
    Some statement [1].
    Another assertion [2].

    ## Sources
    [1] https://arxiv.org/abs/2301.00001
    [2] Vaswani et al. Attention Is All You Need, 2017.
    """
    sources_map = parse_sources_section(doc)
    assert sources_map.get("1") == "https://arxiv.org/abs/2301.00001"
    assert "Attention Is All You Need" in sources_map.get("2", "")


def test_triage_citation_supported() -> None:
    source_text = (
        "Our experimental evaluation demonstrates that the proposed algorithm "
        "reduces training latency by 42.5% on ImageNet."
    )
    sentence = "The proposed algorithm reduces training latency by 42.5% on ImageNet [1]."

    verdict, details = triage_citation(sentence=sentence, cited_text=source_text)
    assert verdict == "supported"
    assert "confirmed" in details or "match" in details


def test_triage_citation_numeric_discrepancy_partial() -> None:
    # Source says 42.5%, but sentence claims 85%
    source_text = (
        "Our experimental evaluation demonstrates that the proposed algorithm "
        "reduces training latency by 42.5% on ImageNet."
    )
    sentence = "The proposed algorithm reduces training latency by 85% on ImageNet [1]."

    verdict, details = triage_citation(sentence=sentence, cited_text=source_text)
    assert verdict == "partially-supported"
    assert "numerical values differ" in details


def test_triage_citation_wrong_source() -> None:
    source_alpha = "Source Alpha discusses quantum computing architectures and qubits."
    source_beta = (
        "Source Beta evaluates autonomous vehicle navigation under dense fog, "
        "achieving a 98.2% collision avoidance rate."
    )

    sentence = (
        "Autonomous vehicle navigation under dense fog achieves a 98.2% collision "
        "avoidance rate [[source-alpha]]."
    )

    all_sources = {
        "source-alpha": source_alpha,
        "source-beta": source_beta,
    }

    verdict, details = triage_citation(
        sentence=sentence,
        cited_text=source_alpha,
        all_sources=all_sources,
    )
    assert verdict == "wrong-source"
    assert "source-beta" in details


def test_triage_citation_unsupported() -> None:
    source_text = "This document exclusively describes database query optimization strategies."
    sentence = "Superconductors were synthesized at ambient pressure and room temperature [1]."

    verdict, details = triage_citation(sentence=sentence, cited_text=source_text)
    assert verdict == "unsupported"


def test_triage_citation_dangling() -> None:
    sentence = "Uncited claim referencing non-existent document [99]."
    verdict, details = triage_citation(sentence=sentence, cited_text=None)
    assert verdict == "dangling"


def test_check_report_file_full_audit(tmp_path: Path) -> None:
    # Setup sources directory
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()

    source_1 = sources_dir / "perf.md"
    source_1.write_text(
        "Benchmarking shows throughput reached 12000 ops/sec across 16 worker nodes.",
        encoding="utf-8",
    )

    source_2 = sources_dir / "security.md"
    source_2.write_text(
        "All egress connections are verified against private IP address ranges.",
        encoding="utf-8",
    )

    # Setup report
    report_file = tmp_path / "report.md"
    report_file.write_text(
        """# Performance & Security Evaluation

Throughput reached 12000 ops/sec across 16 worker nodes [1].
All egress connections are verified against private IP address ranges [[security]].
Throughput reached 99999 ops/sec across 16 worker nodes [1].
Aliens were discovered on Mars [[security]].
Dangling reference without entry [42].

## Sources
[1] perf.md
""",
        encoding="utf-8",
    )

    audit = check_report_file(report_path=report_file, sources_dir=sources_dir)

    assert audit.total_citations == 5
    assert audit.supported == 2
    assert audit.partially_supported == 1
    assert audit.unsupported == 1
    assert audit.dangling == 1
    assert audit.pass_rate == 40.0


def test_cli_web_crawl_and_cite_check(tmp_path: Path) -> None:
    runner = CliRunner()

    # Test cite-check CLI
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "note.md").write_text(
        "System efficiency improved by 35% under load.", encoding="utf-8"
    )

    report_file = tmp_path / "report.md"
    report_file.write_text(
        "System efficiency improved by 35% under load [[note]].\n\n## Sources\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        main,
        ["cite-check", str(report_file), "--sources-dir", str(sources_dir)],
    )
    assert result.exit_code == 0
    assert "Citation Verification Audit" in result.output
    assert "Supported Claims:    1" in result.output
    assert "Pass Rate:           100.0%" in result.output

    # Test cite-check with --json
    result_json = runner.invoke(
        main,
        ["cite-check", str(report_file), "--sources-dir", str(sources_dir), "--json"],
    )
    assert result_json.exit_code == 0
    assert '"supported": 1' in result_json.output

    # Test web-crawl with SSRF block
    res_ssrf = runner.invoke(main, ["web-crawl", "http://127.0.0.1", "--no-browser"])
    assert res_ssrf.exit_code != 0
    assert "SSRF / Security refusal" in res_ssrf.output
