"""Unit test for the init command."""

import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness_agent.cli import main


def test_init_creates_files(tmp_path):
    runner = CliRunner()
    target = tmp_path / "new_project"

    result = runner.invoke(main, ["init", "--target-dir", str(target), "--force"])
    assert result.exit_code == 0
    assert (target / "AGENTS.md").exists()
    assert not (target / "Agent.md").exists()
    assert (target / ".pre-commit-config.yaml").exists()
    assert (target / ".ai" / "plans" / "main").is_dir()
    assert (target / ".ai" / "plans" / "subtasks").is_dir()
    assert not (target / ".ai" / "plan").exists()
    assert (target / ".agents" / "skills" / "sdlc-pretask-checklist" / "SKILL.md").exists()
    assert (target / ".agents" / "skills" / "sdlc-posttask-quality-gate" / "SKILL.md").exists()
    assert (target / ".agents" / "hooks.json").exists()
    assert (target / ".agents" / "hooks" / "enforce_orchestrator.py").exists()
    assert not (target / "src" / "harness_agent").exists()

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


def test_install_ps1_scaffolding(tmp_path: Path) -> None:
    """Test that install.ps1 creates .agents/hooks.json without nested .agents/.agents."""
    ps_executable = shutil.which("powershell") or shutil.which("pwsh")
    if not ps_executable:
        pytest.skip("PowerShell executable not found")

    repo_root = Path(__file__).resolve().parent.parent.parent
    install_script = repo_root / "install.ps1"
    assert install_script.exists()

    target = tmp_path / "ps_scaffold_target"
    target.mkdir(parents=True, exist_ok=True)
    # Pre-create .agents directory to ensure idempotency and test against nested .agents/.agents
    (target / ".agents").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            ps_executable,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(install_script),
            "-TargetDir",
            str(target),
            "-Force",
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    assert (
        result.returncode == 0
    ), f"install.ps1 failed: stdout={result.stdout}, stderr={result.stderr}"
    assert (target / "AGENTS.md").exists()
    assert not (target / "Agent.md").exists()
    assert (target / ".agents" / "hooks.json").exists()
    assert not (target / ".agents" / ".agents").exists()
    assert (target / ".agents" / "hooks" / "enforce_orchestrator.py").exists()
    assert not (target / "src" / "harness_agent").exists()
