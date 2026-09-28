"""Unit tests for the sync command."""

from click.testing import CliRunner

from harness_agent.cli import main


def test_sync_single_project(tmp_path):
    runner = CliRunner()
    target = tmp_path / "sync_project"
    target.mkdir()

    # Pre-populate a custom user file
    (target / "custom_app.py").write_text("print('user code')", encoding="utf-8")

    result = runner.invoke(main, ["sync", str(target)])
    assert result.exit_code == 0
    assert (target / "custom_app.py").exists()
    assert (target / "AGENTS.md").exists()
    assert (target / ".agents" / "skills" / "sdlc-clean-code-standards" / "SKILL.md").exists()


def test_sync_all_projects(tmp_path):
    runner = CliRunner()
    proj1 = tmp_path / "proj1"
    proj2 = tmp_path / "proj2"

    # Init both projects to register them
    runner.invoke(main, ["init", "--target-dir", str(proj1), "--force"])
    runner.invoke(main, ["init", "--target-dir", str(proj2), "--force"])

    # Now run sync --all
    result = runner.invoke(main, ["sync", "--all"])
    assert result.exit_code == 0
    assert (proj1 / "AGENTS.md").exists()
    assert (proj2 / "AGENTS.md").exists()
