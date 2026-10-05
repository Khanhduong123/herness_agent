"""Unit tests for HerdrDispatcher and CLI dispatch command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from harness_agent.cli import main
from harness_agent.core.dispatch import HerdrDispatcher


class TestHerdrDispatcher:
    """Test suite for HerdrDispatcher helper."""

    def test_tc01_is_herdr_available(self) -> None:
        """TC-01: is_herdr_available returns boolean based on shutil.which."""
        with patch("shutil.which", return_value="/usr/local/bin/herdr"):
            assert HerdrDispatcher.is_herdr_available() is True

        with patch("shutil.which", return_value=None):
            assert HerdrDispatcher.is_herdr_available() is False

    def test_tc02_create_agent_worktree_json_parsing(self) -> None:
        """TC-02: create_agent_worktree correctly parses JSON output to extract pane_id."""
        sample_json = json.dumps(
            {
                "id": "cli:worktree:create",
                "result": {
                    "pane_id": "w1B:p1",
                    "checkout_path": "/path/to/worktree",
                    "branch": "agent/subtask_02",
                },
            }
        )
        mock_proc = MagicMock(returncode=0, stdout=sample_json, stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            ok, path, pane_id = HerdrDispatcher.create_agent_worktree("subtask_02")
            assert ok is True
            assert path == "/path/to/worktree"
            assert pane_id == "w1B:p1"
            mock_run.assert_called_once_with(
                ["herdr", "worktree", "create", "--branch", "agent/subtask_02"],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_create_agent_worktree_nested_workspace_id(self) -> None:
        """Test pane_id derivation from workspace_id when pane_id is not explicit."""
        sample_json = json.dumps(
            {
                "result": {
                    "workspace": {"workspace_id": "w22", "worktree": {"checkout_path": "/wt"}},
                }
            }
        )
        mock_proc = MagicMock(returncode=0, stdout=sample_json, stderr="")
        with patch("subprocess.run", return_value=mock_proc):
            ok, path, pane_id = HerdrDispatcher.create_agent_worktree("agent/custom_task")
            assert ok is True
            assert path == "/wt"
            assert pane_id == "w22:p1"

    def test_create_agent_worktree_regex_fallback(self) -> None:
        """Test regex fallback for pane_id when output is plain text."""
        stdout = "Created worktree at C:/wt, opened pane w33:p2 successfully"
        mock_proc = MagicMock(returncode=0, stdout=stdout, stderr="")
        with patch("subprocess.run", return_value=mock_proc):
            ok, path, pane_id = HerdrDispatcher.create_agent_worktree("task_regex")
            assert ok is True
            assert pane_id == "w33:p2"

    def test_create_agent_worktree_failure(self) -> None:
        """Test create_agent_worktree error handling on non-zero exit."""
        mock_proc = MagicMock(returncode=1, stdout="", stderr="Error: branch already exists")
        with patch("subprocess.run", return_value=mock_proc):
            ok, msg, pane_id = HerdrDispatcher.create_agent_worktree("subtask_02")
            assert ok is False
            assert "branch already exists" in msg
            assert pane_id is None

    def test_create_agent_worktree_missing_binary(self) -> None:
        """Test create_agent_worktree when herdr binary is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            ok, msg, pane_id = HerdrDispatcher.create_agent_worktree("subtask_02")
            assert ok is False
            assert "not found" in msg
            assert pane_id is None

    def test_tc03_start_agent_command_construction(self) -> None:
        """TC-03: start_agent builds and executes expected CLI command with permissions flag."""
        mock_proc = MagicMock(returncode=0, stdout="agent ready", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            ok, out = HerdrDispatcher.start_agent(
                task_id="subtask_02",
                pane_id="w1B:p1",
                kind="agy",
                dangerously_skip_permissions=True,
            )
            assert ok is True
            assert out == "agent ready"
            mock_run.assert_called_once_with(
                [
                    "herdr",
                    "agent",
                    "start",
                    "worker_subtask_02",
                    "--kind",
                    "agy",
                    "--pane",
                    "w1B:p1",
                    "--",
                    "--dangerously-skip-permissions",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_start_agent_require_permissions(self) -> None:
        """Test start_agent command when dangerously_skip_permissions is False."""
        mock_proc = MagicMock(returncode=0, stdout="agent ready", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            ok, out = HerdrDispatcher.start_agent(
                task_id="worker_already_prefixed",
                pane_id="w1:p1",
                kind="codex",
                dangerously_skip_permissions=False,
            )
            assert ok is True
            mock_run.assert_called_once_with(
                [
                    "herdr",
                    "agent",
                    "start",
                    "worker_already_prefixed",
                    "--kind",
                    "codex",
                    "--pane",
                    "w1:p1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_start_agent_failure(self) -> None:
        """Test start_agent error handling on non-zero exit."""
        mock_proc = MagicMock(returncode=1, stdout="", stderr="agent_not_ready")
        with patch("subprocess.run", return_value=mock_proc):
            ok, msg = HerdrDispatcher.start_agent("t1", "p1")
            assert ok is False
            assert "agent_not_ready" in msg

    def test_tc04_prompt_agent_execution(self) -> None:
        """TC-04: prompt_agent sends prompt to worker agent."""
        mock_proc = MagicMock(returncode=0, stdout="prompt submitted", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            ok, out = HerdrDispatcher.prompt_agent(
                task_id="subtask_02",
                prompt="Read spec and implement",
                wait=False,
            )
            assert ok is True
            assert out == "prompt submitted"
            mock_run.assert_called_once_with(
                ["herdr", "agent", "prompt", "worker_subtask_02", "Read spec and implement"],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_prompt_agent_with_wait(self) -> None:
        """Test prompt_agent with wait=True."""
        mock_proc = MagicMock(returncode=0, stdout="prompt completed", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            ok, out = HerdrDispatcher.prompt_agent("t1", "do work", wait=True)
            assert ok is True
            mock_run.assert_called_once_with(
                ["herdr", "agent", "prompt", "worker_t1", "do work", "--wait"],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_prompt_agent_failure(self) -> None:
        """Test prompt_agent error handling on non-zero exit."""
        mock_proc = MagicMock(returncode=1, stdout="", stderr="agent_blocked")
        with patch("subprocess.run", return_value=mock_proc):
            ok, msg = HerdrDispatcher.prompt_agent("t1", "prompt")
            assert ok is False
            assert "agent_blocked" in msg


class TestDispatchCliCommand:
    """Test suite for 'harness-agent dispatch' CLI command."""

    def test_tc05_cli_missing_spec_and_prompt(self) -> None:
        """TC-05a: CLI command fails when neither --spec-file nor --prompt is provided."""
        runner = CliRunner()
        result = runner.invoke(main, ["dispatch", "--task-id", "t1"])
        assert result.exit_code != 0
        assert "Either --spec-file or --prompt must be provided" in result.output

    def test_tc05_cli_missing_spec_file_path(self, tmp_path: Path) -> None:
        """TC-05b: CLI command fails when spec file does not exist on disk."""
        runner = CliRunner()
        missing = tmp_path / "nonexistent_spec.md"
        result = runner.invoke(main, ["dispatch", "--task-id", "t1", "--spec-file", str(missing)])
        assert result.exit_code != 0
        assert "Spec file not found" in result.output

    def test_tc05_cli_herdr_unavailable(self, tmp_path: Path) -> None:
        """TC-05c: CLI command fails gracefully when Herdr is not installed."""
        runner = CliRunner()
        spec = tmp_path / "subtask.md"
        spec.write_text("Spec content", encoding="utf-8")

        with patch.object(HerdrDispatcher, "is_herdr_available", return_value=False):
            result = runner.invoke(main, ["dispatch", "--task-id", "t1", "--spec-file", str(spec)])
            assert result.exit_code != 0
            assert "Herdr CLI is not installed" in result.output

    def test_tc05_cli_herdr_worktree_error(self, tmp_path: Path) -> None:
        """TC-05d: CLI command fails gracefully when worktree creation fails."""
        runner = CliRunner()
        spec = tmp_path / "subtask.md"
        spec.write_text("Spec content", encoding="utf-8")

        with (
            patch.object(HerdrDispatcher, "is_herdr_available", return_value=True),
            patch.object(
                HerdrDispatcher,
                "create_agent_worktree",
                return_value=(False, "Failed to checkout", None),
            ),
        ):
            result = runner.invoke(main, ["dispatch", "--task-id", "t1", "--spec-file", str(spec)])
            assert result.exit_code != 0
            assert "Failed to create worktree: Failed to checkout" in result.output

    def test_tc05_cli_successful_dispatch_with_spec_file(self, tmp_path: Path) -> None:
        """TC-05e: Successful dispatch using --spec-file."""
        runner = CliRunner()
        spec = tmp_path / "subtask.md"
        spec.write_text("Implement feature", encoding="utf-8")

        with (
            patch.object(HerdrDispatcher, "is_herdr_available", return_value=True),
            patch.object(
                HerdrDispatcher,
                "create_agent_worktree",
                return_value=(True, str(tmp_path), "w1:p1"),
            ),
            patch.object(
                HerdrDispatcher,
                "start_agent",
                return_value=(True, "agent ready"),
            ) as mock_start,
            patch.object(
                HerdrDispatcher,
                "prompt_agent",
                return_value=(True, "prompt sent"),
            ) as mock_prompt,
        ):
            result = runner.invoke(
                main,
                ["dispatch", "--task-id", "subtask_02", "--spec-file", str(spec)],
            )
            assert result.exit_code == 0
            assert (
                "Dispatched task 'subtask_02' to worker_subtask_02 successfully!" in result.output
            )
            mock_start.assert_called_once_with(
                task_id="subtask_02",
                pane_id="w1:p1",
                kind="agy",
                dangerously_skip_permissions=True,
            )
            mock_prompt.assert_called_once()
            call_prompt_kwargs = mock_prompt.call_args.kwargs
            assert "Read " in call_prompt_kwargs["prompt"]

    def test_tc05_cli_successful_dispatch_with_prompt_override(self) -> None:
        """TC-05f: Successful dispatch using custom --prompt override."""
        runner = CliRunner()
        with (
            patch.object(HerdrDispatcher, "is_herdr_available", return_value=True),
            patch.object(
                HerdrDispatcher,
                "create_agent_worktree",
                return_value=(True, "/tmp/wt", "w2:p1"),
            ),
            patch.object(
                HerdrDispatcher,
                "start_agent",
                return_value=(True, "agent ready"),
            ),
            patch.object(
                HerdrDispatcher,
                "prompt_agent",
                return_value=(True, "prompt sent"),
            ) as mock_prompt,
        ):
            result = runner.invoke(
                main,
                [
                    "dispatch",
                    "--task-id",
                    "t99",
                    "--prompt",
                    "Custom instruction prompt",
                    "--kind",
                    "codex",
                    "--require-permissions",
                ],
            )
            assert result.exit_code == 0
            assert "Dispatched task 't99' to worker_t99 successfully!" in result.output
            mock_prompt.assert_called_once_with(
                task_id="t99",
                prompt="Custom instruction prompt",
                wait=False,
            )
