"""Unit test for the init command."""

from click.testing import CliRunner

from harness_agent.cli import main


def test_init_creates_files(tmp_path):
    runner = CliRunner()
    target = tmp_path / "new_project"

    result = runner.invoke(main, ["init", "--target-dir", str(target), "--force"])
    assert result.exit_code == 0
    assert (target / "AGENTS.md").exists()
    assert (target / ".pre-commit-config.yaml").exists()
    assert (target / ".ai" / "plans" / "main").is_dir()
    assert (target / ".ai" / "plans" / "subtasks").is_dir()
    assert not (target / ".ai" / "plan").exists()
    assert (target / ".agents" / "skills" / "sdlc-pretask-checklist" / "SKILL.md").exists()
    assert (target / ".agents" / "skills" / "sdlc-posttask-quality-gate" / "SKILL.md").exists()

    pre_commit_content = (target / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "no-commit-to-branch" in pre_commit_content
    assert "dev" in pre_commit_content
    assert "main" in pre_commit_content

    agents_content = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "RULE 0: ZERO-TOLERANCE CODE-WRITING LOCK" in agents_content
    assert "NO AUTOMATED MERGING" in agents_content


def test_init_existing_directory_prompt_cancel(tmp_path):
    runner = CliRunner()
    target = tmp_path / "existing_project"
    target.mkdir()
    (target / "app.py").write_text("print('hello')", encoding="utf-8")

    # User enters 'n' to cancel
    result = runner.invoke(main, ["init", "--target-dir", str(target)], input="n\n")
    assert result.exit_code == 0
    assert "Đã hủy thiết lập" in result.output
    # Existing file untouched
    assert (target / "app.py").exists()


def test_init_existing_directory_merge(tmp_path):
    runner = CliRunner()
    target = tmp_path / "existing_project_merge"
    target.mkdir()
    (target / "app.py").write_text("print('hello')", encoding="utf-8")

    # User enters 'y' to merge / update
    result = runner.invoke(main, ["init", "--target-dir", str(target)], input="y\n")
    assert result.exit_code == 0
    assert (target / "app.py").exists()
    assert (target / "AGENTS.md").exists()
    assert (target / ".agents" / "skills" / "sdlc-pretask-checklist" / "SKILL.md").exists()
