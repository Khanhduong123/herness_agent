"""Tests for CLI default options and command configurations."""

import pytest

from harness_agent.cli import orchestrate_cmd, resume_cmd, run_suite_cmd


def test_cli_default_output_options() -> None:
    """Assert default output option for orchestrate, resume, and run-suite point to .runs/."""
    # Check run-suite default output
    run_suite_output = next(p for p in run_suite_cmd.params if p.name == "output")
    assert run_suite_output.default == ".runs/eval_report.json"

    # Check orchestrate default output
    orchestrate_output = next(p for p in orchestrate_cmd.params if p.name == "output")
    assert orchestrate_output.default == ".runs/orchestration_report.json"

    # Check resume default output
    resume_output = next(p for p in resume_cmd.params if p.name == "output")
    assert resume_output.default == ".runs/orchestration_report.json"


@pytest.mark.parametrize(
    "cmd,expected_default",
    [
        (run_suite_cmd, ".runs/eval_report.json"),
        (orchestrate_cmd, ".runs/orchestration_report.json"),
        (resume_cmd, ".runs/orchestration_report.json"),
    ],
)
def test_cli_commands_have_dot_runs_output(cmd, expected_default: str) -> None:
    """Parametrized verification of .runs/ output defaults across CLI commands."""
    output_param = next(p for p in cmd.params if p.name == "output")
    assert output_param.default == expected_default
