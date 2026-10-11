"""Unit tests for coverage report parsing, gap prompt generation, and quality gates."""

import pytest

from harness_agent.core.models import AgentRole, RunResult, SubTask, Task, TaskCheck
from harness_agent.core.orchestrator import AgentOrchestrator
from harness_agent.evaluation.evaluator import (
    CoverageGateEvaluator,
    CoverageQualityGateError,
    CoverageSummary,
    build_coverage_gap_prompt,
    evaluate_coverage_gate,
    evaluate_task,
    parse_coverage_report,
)


def test_tc01_normal_coverage_parse_above_threshold():
    """TC-01: Normal coverage parse (>80%) - Gate passes."""
    cov_text = """
---------- coverage: platform win32, python 3.10 ----------
Name                      Stmts   Miss  Cover   Missing
-------------------------------------------------------
src/foo.py                   20      2    90%   15-16
src/bar.py                   20      4    80%   22-25
-------------------------------------------------------
TOTAL                        40      6    85%
"""
    summary = parse_coverage_report(cov_text)
    assert summary.total_coverage == 85.0
    assert summary.passed is True
    assert "src/foo.py" in summary.missed_lines_by_file
    assert summary.missed_lines_by_file["src/foo.py"] == ["15-16"]
    assert "src/bar.py" in summary.missed_lines_by_file
    assert summary.missed_lines_by_file["src/bar.py"] == ["22-25"]

    gate_result = evaluate_coverage_gate(summary, threshold=80.0)
    assert gate_result is True


def test_tc02_under_threshold_coverage_fails_gate():
    """TC-02: Under-threshold coverage (<80%) - Gate fails and raises error."""
    cov_text = """
Name                      Stmts   Miss  Cover   Missing
-------------------------------------------------------
src/foo.py                   20      7    65%   10-16
-------------------------------------------------------
TOTAL                        20      7    65%
"""
    summary = parse_coverage_report(cov_text)
    assert summary.total_coverage == 65.0
    assert summary.passed is False

    with pytest.raises(CoverageQualityGateError) as exc_info:
        evaluate_coverage_gate(summary, threshold=80.0)

    err = exc_info.value
    assert err.coverage.total_coverage == 65.0
    assert "65.00% < 80.00%" in str(err)
    assert "src/foo.py" in str(err)
    assert "10-16" in str(err)


def test_tc03_empty_and_malformed_coverage_output():
    """TC-03: Empty/malformed coverage output defaults to 0.0% without crashing."""
    # Empty string
    summary_empty = parse_coverage_report("")
    assert summary_empty.total_coverage == 0.0
    assert summary_empty.passed is False
    assert len(summary_empty.missed_lines_by_file) == 0

    # Malformed whitespace/garbage text
    summary_garbage = parse_coverage_report("random text without coverage tables\nsome error log")
    assert summary_garbage.total_coverage == 0.0
    assert summary_garbage.passed is False


def test_tc04_gap_prompt_generation():
    """TC-04: Gap prompt generation details files and missed line numbers."""
    summary = CoverageSummary(
        total_coverage=75.0,
        missed_lines_by_file={"core/runner.py": ["12-18", "45"], "core/models.py": ["102"]},
        passed=False,
    )
    prompt = build_coverage_gap_prompt(summary)

    assert "Coverage Quality Gate Status: FAILED" in prompt
    assert "75.00%" in prompt
    assert "`core/runner.py`: lines 12-18, 45" in prompt
    assert "`core/models.py`: lines 102" in prompt
    assert "Action Required: Please write unit tests covering the missed branches" in prompt


def test_edge_case_100_percent_coverage():
    """Edge Case: 100% full coverage with no missed lines."""
    cov_text = """
Name                      Stmts   Miss  Cover   Missing
-------------------------------------------------------
src/perfect.py               50      0   100%
-------------------------------------------------------
TOTAL                        50      0   100%
"""
    summary = parse_coverage_report(cov_text)
    assert summary.total_coverage == 100.0
    assert summary.passed is True
    assert len(summary.missed_lines_by_file) == 0

    prompt = build_coverage_gap_prompt(summary)
    assert "All statements and branches are fully covered by unit tests." in prompt
    assert evaluate_coverage_gate(summary, threshold=80.0) is True


def test_edge_case_threshold_boundary_comparison():
    """Edge Case: Strict float comparison (79.99% vs 80.0%)."""
    summary_below = CoverageSummary(total_coverage=79.99, passed=False)
    with pytest.raises(CoverageQualityGateError):
        evaluate_coverage_gate(summary_below, threshold=80.0)

    summary_exact = CoverageSummary(total_coverage=80.0, passed=False)
    assert evaluate_coverage_gate(summary_exact, threshold=80.0) is True
    assert summary_exact.passed is True


def test_json_coverage_report_parsing():
    """Coverage report in JSON format (pytest --cov-report=json)."""
    json_output = """{
        "meta": {"version": "7.4.0"},
        "totals": {
            "percent_covered": 88.5,
            "covered_lines": 177,
            "missing_lines": 23
        },
        "files": {
            "src/module_a.py": {
                "missing_lines": [10, 11, 12, 20]
            },
            "src/module_b.py": {
                "missing_lines": []
            }
        }
    }"""
    summary = parse_coverage_report(json_output)
    assert summary.total_coverage == 88.5
    assert summary.passed is True
    assert "src/module_a.py" in summary.missed_lines_by_file
    assert summary.missed_lines_by_file["src/module_a.py"] == ["10-12", "20"]
    assert "src/module_b.py" not in summary.missed_lines_by_file


def test_coverage_gate_evaluator_integration():
    """Test CoverageGateEvaluator in evaluator registry and task check evaluation."""
    evaluator = CoverageGateEvaluator()
    check = TaskCheck(type="coverage_gate", target="80.0")

    passing_res = RunResult(
        task_id="t1",
        success=True,
        exit_code=0,
        duration_seconds=1.0,
        output_text="""
Name          Stmts   Miss  Cover
---------------------------------
TOTAL           100     10    90%
""",
    )
    passed, msg = evaluator.evaluate(check, passing_res, ".")
    assert passed is True
    assert "Coverage gate passed (90.00% >= 80.00%)" in msg

    failing_res = RunResult(
        task_id="t2",
        success=True,
        exit_code=0,
        duration_seconds=1.0,
        output_text="""
Name          Stmts   Miss  Cover
---------------------------------
TOTAL           100     30    70%
""",
    )
    failed, fail_msg = evaluator.evaluate(check, failing_res, ".")
    assert failed is False
    assert "Coverage quality gate failed" in fail_msg

    # Test via evaluate_task wrapper
    task = Task(
        id="t_cov",
        name="Coverage Task",
        prompt="run tests",
        checks=[TaskCheck(type="coverage_gate", target="80.0")],
    )
    results = evaluate_task(task, failing_res, ".")
    assert results["coverage_gate_0_80.0"] is False
    assert failing_res.success is False


def test_orchestrator_coverage_methods():
    """Test AgentOrchestrator evaluate_coverage_gate and create_coverage_remediation_task."""
    orchestrator = AgentOrchestrator()
    summary_ok = CoverageSummary(total_coverage=85.0, passed=True)
    assert orchestrator.evaluate_coverage_gate(summary_ok, min_coverage=80.0) is True

    summary_bad = CoverageSummary(
        total_coverage=60.0,
        missed_lines_by_file={"src/api.py": ["15-20"]},
        passed=False,
    )
    with pytest.raises(CoverageQualityGateError):
        orchestrator.evaluate_coverage_gate(summary_bad, min_coverage=80.0)

    subtask = SubTask(
        id="subtask_test",
        name="Implement Unit Tests",
        instruction="Write tests",
        role=AgentRole.TESTER,
    )
    remediation_task = orchestrator.create_coverage_remediation_task(subtask, summary_bad)
    assert remediation_task.id == "subtask_test_coverage_gap"
    assert remediation_task.role == AgentRole.TESTER
    assert "src/api.py" in remediation_task.instruction
    assert "60.00%" in remediation_task.instruction
    assert "subtask_test" in remediation_task.depends_on
