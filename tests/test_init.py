"""Unit test for the init command."""

from click.testing import CliRunner

from harness_agent.cli import main


def test_init_creates_files(tmp_path):
    runner = CliRunner()
    target = tmp_path / "new_project"

    result = runner.invoke(main, ["init", str(target)])
    assert result.exit_code == 0
    assert (target / "Agent.md").exists()
    assert (target / "AGENTS.md").exists()
    assert (target / ".pre-commit-config.yaml").exists()
    assert (target / "examples" / "orchestrator_plan.yaml").exists()
