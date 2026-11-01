"""Unit tests for GitCLIUpdater and harness-agent update command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from harness_agent.cli import main
from harness_agent.core.updater import GitCLIUpdater, UpdateResult


@pytest.fixture
def updater(tmp_path: Path) -> GitCLIUpdater:
    """Fixture providing a GitCLIUpdater instance initialized with a temporary directory."""
    return GitCLIUpdater(repo_root=tmp_path)


def test_check_clean_worktree_clean(updater: GitCLIUpdater) -> None:
    """Test 1: Returns (True, '') when worktree status is clean."""
    mock_res = MagicMock(returncode=0, stdout="", stderr="")
    with patch("subprocess.run", return_value=mock_res):
        is_clean, dirty_info = updater.check_clean_worktree()
        assert is_clean is True
        assert dirty_info == ""


def test_check_clean_worktree_dirty(updater: GitCLIUpdater) -> None:
    """Test 2: Returns (False, dirty_files) when worktree has changes."""
    mock_res = MagicMock(returncode=0, stdout=" M src/cli.py\n?? untracked.txt", stderr="")
    with patch("subprocess.run", return_value=mock_res):
        is_clean, dirty_info = updater.check_clean_worktree()
        assert is_clean is False
        assert "src/cli.py" in dirty_info


def test_update_aborts_on_dirty_worktree_without_force(updater: GitCLIUpdater) -> None:
    """Test 3: Verifies safe abort without calling git pull when worktree is dirty."""
    with (
        patch.object(updater, "_is_git_repository", return_value=True),
        patch.object(updater, "get_current_commit", return_value="abc1234"),
        patch.object(updater, "check_clean_worktree", return_value=(False, "M file.py")),
        patch.object(updater, "run_git_pull") as mock_pull,
    ):

        result = updater.update(force=False)
        assert result.success is False
        assert "uncommitted changes" in result.message
        mock_pull.assert_not_called()


def test_update_proceeds_with_force_on_dirty_worktree(updater: GitCLIUpdater) -> None:
    """Test 4: Verifies update runs when force=True even on dirty worktree."""
    with (
        patch.object(updater, "_is_git_repository", return_value=True),
        patch.object(updater, "get_current_commit", side_effect=["abc1234", "def5678"]),
        patch.object(updater, "check_clean_worktree", return_value=(False, "M file.py")),
        patch.object(updater, "run_git_pull", return_value=(True, "Updating abc..def")),
        patch.object(updater, "resync_editable_install", return_value=(True, "Success")),
        patch.object(updater, "run_smoke_verification", return_value=(True, "All passed")),
    ):

        result = updater.update(force=True)
        assert result.success is True
        assert result.old_commit == "abc1234"
        assert result.new_commit == "def5678"


def test_update_already_up_to_date(updater: GitCLIUpdater) -> None:
    """Test 5: Verifies early exit with already_up_to_date=True when already up to date."""
    with (
        patch.object(updater, "_is_git_repository", return_value=True),
        patch.object(updater, "get_current_commit", return_value="abc1234"),
        patch.object(updater, "check_clean_worktree", return_value=(True, "")),
        patch.object(updater, "run_git_pull", return_value=(True, "Already up to date.")),
        patch.object(updater, "resync_editable_install") as mock_pip,
        patch.object(updater, "run_smoke_verification", return_value=(True, "OK")),
    ):

        result = updater.update(force=False)
        assert result.success is True
        assert result.already_up_to_date is True
        assert "Already up to date" in result.message
        mock_pip.assert_not_called()


def test_update_success_flow(updater: GitCLIUpdater) -> None:
    """Test 6: Verifies git pull -> pip install -> smoke probe -> commit SHA update."""
    with (
        patch.object(updater, "_is_git_repository", return_value=True),
        patch.object(updater, "get_current_commit", side_effect=["1111111", "2222222"]),
        patch.object(updater, "check_clean_worktree", return_value=(True, "")),
        patch.object(updater, "run_git_pull", return_value=(True, "Fast-forward")),
        patch.object(updater, "resync_editable_install", return_value=(True, "Installed")),
        patch.object(updater, "run_smoke_verification", return_value=(True, "Verified")),
    ):

        result = updater.update()
        assert result.success is True
        assert result.already_up_to_date is False
        assert result.old_commit == "1111111"
        assert result.new_commit == "2222222"
        assert "1111111 -> 2222222" in result.message


def test_update_git_pull_failure(updater: GitCLIUpdater) -> None:
    """Test 7: Verifies error propagation when git pull exits non-zero."""
    with (
        patch.object(updater, "_is_git_repository", return_value=True),
        patch.object(updater, "get_current_commit", return_value="1111111"),
        patch.object(updater, "check_clean_worktree", return_value=(True, "")),
        patch.object(updater, "run_git_pull", return_value=(False, "Could not resolve host")),
        patch.object(updater, "resync_editable_install") as mock_pip,
    ):

        result = updater.update()
        assert result.success is False
        assert "[ERROR] Failed to pull from remote" in result.message
        mock_pip.assert_not_called()


def test_cli_update_command_execution() -> None:
    """Test 8: Verifies Click CLI test runner execution for harness-agent update."""
    runner = CliRunner()

    mock_res_ok = UpdateResult(
        success=True,
        already_up_to_date=True,
        old_commit="abc1234",
        new_commit="abc1234",
        message="Already up to date. CLI is current.",
    )
    with patch("harness_agent.core.updater.GitCLIUpdater.update", return_value=mock_res_ok):
        res = runner.invoke(main, ["update"])
        assert res.exit_code == 0
        assert "[OK] Already up to date" in res.output

    mock_res_err = UpdateResult(
        success=False,
        message="Aborted: Working directory has uncommitted changes.",
    )
    with patch("harness_agent.core.updater.GitCLIUpdater.update", return_value=mock_res_err):
        res = runner.invoke(main, ["update"])
        assert res.exit_code == 1
        assert "[ERROR] Aborted: Working directory has uncommitted changes." in res.output
