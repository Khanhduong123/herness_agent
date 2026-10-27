"""Tests for CLI default options and command configurations."""

import pytest
from click.testing import CliRunner

from harness_agent.cli import main, orchestrate_cmd, resume_cmd, review_cmd, run_suite_cmd


def test_cli_default_output_options() -> None:
    """Assert default output option for commands points to .runs/."""
    # Check run-suite default output
    run_suite_output = next(p for p in run_suite_cmd.params if p.name == "output")
    assert run_suite_output.default == ".runs/eval_report.json"

    # Check orchestrate default output
    orchestrate_output = next(p for p in orchestrate_cmd.params if p.name == "output")
    assert orchestrate_output.default == ".runs/orchestration_report.json"

    # Check resume default output
    resume_output = next(p for p in resume_cmd.params if p.name == "output")
    assert resume_output.default == ".runs/orchestration_report.json"

    # Check review default output
    review_output = next(p for p in review_cmd.params if p.name == "output")
    assert review_output.default == ".runs/critics_report.json"


@pytest.mark.parametrize(
    "cmd,expected_default",
    [
        (run_suite_cmd, ".runs/eval_report.json"),
        (orchestrate_cmd, ".runs/orchestration_report.json"),
        (resume_cmd, ".runs/orchestration_report.json"),
        (review_cmd, ".runs/critics_report.json"),
    ],
)
def test_cli_commands_have_dot_runs_output(cmd, expected_default: str) -> None:
    """Parametrized verification of .runs/ output defaults across CLI commands."""
    output_param = next(p for p in cmd.params if p.name == "output")
    assert output_param.default == expected_default


def test_ensure_gitignore_preserves_custom_content_and_appends_harness(tmp_path) -> None:
    """Verifies that _ensure_gitignore preserves existing entries and appends missing entries."""
    from harness_agent.cli import _ensure_gitignore

    target_dir = tmp_path / "my_project"
    target_dir.mkdir()
    gitignore = target_dir / ".gitignore"
    initial_content = "# User custom entries\nnode_modules/\n.venv/\n*.log\n"
    gitignore.write_text(initial_content, encoding="utf-8")

    _ensure_gitignore(target_dir)

    result_content = gitignore.read_text(encoding="utf-8")
    assert "node_modules/" in result_content
    assert ".venv/" in result_content
    assert "*.log" in result_content
    assert "# Harness Agent & AI Orchestration" in result_content
    assert ".agents/" in result_content
    assert ".runs/" in result_content
    assert ".ai/" in result_content
    assert ".worktrees/" in result_content
    assert "AGENTS.md" in result_content

    # Running it again should be idempotent and not duplicate entries
    _ensure_gitignore(target_dir)
    double_content = gitignore.read_text(encoding="utf-8")
    assert double_content.count(".agents/") == 1
    assert double_content.count("AGENTS.md") == 1


def test_sync_single_project_does_not_overwrite_precommit(tmp_path) -> None:
    """Verifies _sync_single_project does not overwrite user existing .pre-commit-config.yaml."""
    from harness_agent.cli import _sync_single_project

    repo_root = tmp_path / "harness_root"
    repo_root.mkdir()
    (repo_root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (repo_root / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: dummy\n    hooks:\n      - id: dummy-hook\n",
        encoding="utf-8",
    )

    target_proj = tmp_path / "target_proj"
    target_proj.mkdir()
    user_precommit = target_proj / ".pre-commit-config.yaml"
    user_custom_hooks = (
        "repos:\n"
        "  - repo: https://github.com/psf/black\n"
        "    rev: 23.3.0\n"
        "    hooks:\n"
        "      - id: black\n"
    )
    user_precommit.write_text(user_custom_hooks, encoding="utf-8")

    _sync_single_project(repo_root, target_proj)

    final_precommit = user_precommit.read_text(encoding="utf-8")
    # Must preserve existing black hook
    assert "https://github.com/psf/black" in final_precommit
    assert "id: black" in final_precommit
    # Must append no-commit-to-branch hook safely
    assert "no-commit-to-branch" in final_precommit
    # Must not contain dummy-hook from template
    assert "dummy-hook" not in final_precommit


def test_cli_runner_help_command() -> None:
    """Verifies Click CliRunner executes --help cleanly."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "smoke" in result.output
    assert "check" in result.output


def test_cli_runner_check_command() -> None:
    """Verifies Click CliRunner executes check command successfully."""
    runner = CliRunner()
    result = runner.invoke(main, ["check"])
    assert result.exit_code == 0
    assert "[OK] agy is ready" in result.output


def test_cli_runner_smoke_command() -> None:
    """Verifies Click CliRunner executes smoke command successfully."""
    runner = CliRunner()
    result = runner.invoke(main, ["smoke"])
    assert result.exit_code == 0
    assert "[SMOKE PROBE]" in result.output
    assert "[PASSED] All smoke probes succeeded" in result.output
