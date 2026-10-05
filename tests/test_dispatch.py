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
        """TC-03: start_agent builds CLI command with permissions and effort flag."""
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
                    "--effort",
                    "low",
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
                effort="",
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

    def test_start_agent_custom_effort(self) -> None:
        """Test start_agent command with custom effort string."""
        mock_proc = MagicMock(returncode=0, stdout="agent ready", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            ok, out = HerdrDispatcher.start_agent(
                task_id="t1",
                pane_id="w1:p1",
                kind="agy",
                dangerously_skip_permissions=False,
                effort="high",
            )
            assert ok is True
            mock_run.assert_called_once_with(
                [
                    "herdr",
                    "agent",
                    "start",
                    "worker_t1",
                    "--kind",
                    "agy",
                    "--pane",
                    "w1:p1",
                    "--",
                    "--effort",
                    "high",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_start_agent_effort_none_and_medium(self) -> None:
        """Test start_agent command with effort='none' and effort='medium'."""
        mock_proc = MagicMock(returncode=0, stdout="agent ready", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            ok, out = HerdrDispatcher.start_agent(
                task_id="t_none",
                pane_id="w1:p1",
                kind="agy",
                dangerously_skip_permissions=True,
                effort="none",
            )
            assert ok is True
            mock_run.assert_called_with(
                [
                    "herdr",
                    "agent",
                    "start",
                    "worker_t_none",
                    "--kind",
                    "agy",
                    "--pane",
                    "w1:p1",
                    "--",
                    "--dangerously-skip-permissions",
                    "--effort",
                    "none",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        with patch("subprocess.run", return_value=mock_proc) as mock_run2:
            ok2, out2 = HerdrDispatcher.start_agent(
                task_id="t_med",
                pane_id="w2:p1",
                kind="agy",
                dangerously_skip_permissions=False,
                effort="medium",
            )
            assert ok2 is True
            mock_run2.assert_called_with(
                [
                    "herdr",
                    "agent",
                    "start",
                    "worker_t_med",
                    "--kind",
                    "agy",
                    "--pane",
                    "w2:p1",
                    "--",
                    "--effort",
                    "medium",
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

    def test_dispatch_interactive_critics_herdr_unavailable(self) -> None:
        """dispatch_interactive_critics returns False when Herdr is unavailable."""
        with patch.object(HerdrDispatcher, "is_herdr_available", return_value=False):
            ok, msg = HerdrDispatcher.dispatch_interactive_critics(base_ref="main")
            assert ok is False
            assert "Herdr CLI 'herdr' is not installed" in msg

    def test_dispatch_interactive_critics_success(self) -> None:
        """dispatch_interactive_critics splits pane, starts agent, and sends prompted diff."""
        diff_out = "diff --git a/file.py b/file.py\n+x = 1\n"
        diff_proc = MagicMock(returncode=0, stdout=diff_out, stderr="")
        split_proc = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": {"pane_id": "critics:p2"}}),
            stderr="",
        )
        start_proc = MagicMock(returncode=0, stdout="agent started", stderr="")
        prompt_proc = MagicMock(returncode=0, stdout="prompt sent", stderr="")

        with (
            patch.object(HerdrDispatcher, "is_herdr_available", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[diff_proc, split_proc, start_proc, prompt_proc],
            ) as mock_run,
        ):
            ok, msg = HerdrDispatcher.dispatch_interactive_critics(
                base_ref="main",
                task_id="subtask_02",
            )
            assert ok is True
            assert "Dispatched interactive critic inspection agent" in msg
            assert "critics:p2" in msg

            # Verify prompt content includes role anchor
            prompt_call = mock_run.call_args_list[3]
            prompt_cmd = prompt_call[0][0]
            assert "agent" in prompt_cmd and "prompt" in prompt_cmd
            prompt_text = prompt_cmd[-1]
            assert "[SYSTEM CONTEXT: You are an Adversarial Critic Agent" in prompt_text
            assert "STATUS: APPROVED" in prompt_text

    def test_dispatch_interactive_critics_split_failure(self) -> None:
        """dispatch_interactive_critics handles split pane failure gracefully."""
        diff_proc = MagicMock(returncode=0, stdout="diff --git a/a b/b\n", stderr="")
        split_proc = MagicMock(returncode=1, stdout="", stderr="failed to split pane")

        with (
            patch.object(HerdrDispatcher, "is_herdr_available", return_value=True),
            patch("subprocess.run", side_effect=[diff_proc, split_proc, split_proc]),
        ):
            ok, msg = HerdrDispatcher.dispatch_interactive_critics(base_ref="main")
            assert ok is False
            assert "Failed to create Herdr split pane" in msg


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

    def test_tc05g_cli_dispatch_with_feature_flag(self, tmp_path: Path) -> None:
        """TC-05g: Dispatch with --feature flag passes base_ref to create_agent_worktree."""
        runner = CliRunner()
        spec = tmp_path / "spec.md"
        spec.write_text("Spec content", encoding="utf-8")

        with (
            patch.object(HerdrDispatcher, "is_herdr_available", return_value=True),
            patch.object(
                HerdrDispatcher,
                "create_agent_worktree",
                return_value=(True, str(tmp_path), "w1:p1"),
            ) as mock_wt,
            patch.object(HerdrDispatcher, "start_agent", return_value=(True, "ok")),
            patch.object(HerdrDispatcher, "prompt_agent", return_value=(True, "ok")),
        ):
            result = runner.invoke(
                main,
                [
                    "dispatch",
                    "--task-id",
                    "t1",
                    "--spec-file",
                    str(spec),
                    "--feature",
                    "feat/resilience",
                ],
            )
            assert result.exit_code == 0
            mock_wt.assert_called_once_with("t1", base_ref="feat/resilience")


class TestHerdrDispatcherLifecycle:
    """Test suite for blocking wait, feature branch, worktree merge, and lifecycle safety."""

    def test_wait_for_task_immediate(self, tmp_path: Path) -> None:
        """wait_for_task returns content immediately when status file exists."""
        status_dir = tmp_path / ".ai" / "status"
        status_dir.mkdir(parents=True, exist_ok=True)
        flag = status_dir / "task_01.complete"
        flag.write_text("DONE_OK", encoding="utf-8")

        ok, msg = HerdrDispatcher.wait_for_task(
            "task_01", timeout_seconds=2, poll_interval=0.01, status_dir=status_dir
        )
        assert ok is True
        assert msg == "DONE_OK"

    def test_wait_for_task_clean_prefix(self, tmp_path: Path) -> None:
        """wait_for_task strips agent/ prefix when searching for flag file."""
        status_dir = tmp_path / ".ai" / "status"
        status_dir.mkdir(parents=True, exist_ok=True)
        flag = status_dir / "my_subtask.complete"
        flag.write_text("", encoding="utf-8")

        ok, msg = HerdrDispatcher.wait_for_task(
            "agent/my_subtask", timeout_seconds=2, poll_interval=0.01, status_dir=status_dir
        )
        assert ok is True
        assert msg == "[WORKER_COMPLETED]"

    def test_wait_for_task_checks_worktree_status(self, tmp_path: Path) -> None:
        """wait_for_task successfully detects completion flag inside worktree .ai/status."""
        wt_status = tmp_path / ".worktrees" / "agent" / "subtask_wt" / ".ai" / "status"
        wt_status.mkdir(parents=True, exist_ok=True)
        flag = wt_status / "subtask_wt.complete"
        flag.write_text("[WORKER_COMPLETED]", encoding="utf-8")

        ok, msg = HerdrDispatcher.wait_for_task(
            "subtask_wt",
            timeout_seconds=2,
            poll_interval=0.01,
            repo_root=tmp_path,
        )
        assert ok is True
        assert msg == "[WORKER_COMPLETED]"

    def test_wait_for_task_timeout(self, tmp_path: Path) -> None:
        """wait_for_task returns False after timeout expires."""
        status_dir = tmp_path / ".ai" / "status"
        status_dir.mkdir(parents=True, exist_ok=True)

        ok, msg = HerdrDispatcher.wait_for_task(
            "nonexistent", timeout_seconds=0, poll_interval=0.01, status_dir=status_dir
        )
        assert ok is False
        assert "timed out after 0s" in msg

    def test_create_feature_branch_dirty_tree(self) -> None:
        """create_feature_branch fails if working tree is dirty."""
        mock_proc = MagicMock(returncode=0, stdout=" M src/foo.py\n", stderr="")
        with patch("subprocess.run", return_value=mock_proc):
            ok, msg = HerdrDispatcher.create_feature_branch("new_feat")
            assert ok is False
            assert "Working tree is dirty" in msg

    def test_create_feature_branch_success(self) -> None:
        """create_feature_branch successfully creates feat/ branch."""
        status_proc = MagicMock(returncode=0, stdout="", stderr="")
        checkout_proc = MagicMock(returncode=0, stdout="Switched to new branch", stderr="")
        with patch("subprocess.run", side_effect=[status_proc, checkout_proc]) as mock_run:
            ok, msg = HerdrDispatcher.create_feature_branch("my-feature", base_branch="main")
            assert ok is True
            assert "Created and checked out branch 'feat/my-feature'" in msg
            assert mock_run.call_count == 2
            mock_run.assert_called_with(
                ["git", "checkout", "-b", "feat/my-feature", "main"],
                cwd=None,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_create_feature_branch_failure(self) -> None:
        """create_feature_branch handles git checkout failure."""
        status_proc = MagicMock(returncode=0, stdout="", stderr="")
        checkout_proc = MagicMock(returncode=1, stdout="", stderr="fatal: branch already exists")
        with patch("subprocess.run", side_effect=[status_proc, checkout_proc]):
            ok, msg = HerdrDispatcher.create_feature_branch("feat/existing")
            assert ok is False
            assert "fatal: branch already exists" in msg

    def test_setup_worktree_env(self, tmp_path: Path) -> None:
        """setup_worktree_env copies all available .env* and .flake8 files."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        wt = tmp_path / "worktree"
        wt.mkdir()

        (repo_root / ".env").write_text("KEY=1", encoding="utf-8")
        (repo_root / ".env.test").write_text("TEST=true", encoding="utf-8")
        (repo_root / ".flake8").write_text("[flake8]\n", encoding="utf-8")

        copied = HerdrDispatcher.setup_worktree_env(worktree_path=wt, repo_root=repo_root)
        assert ".env" in copied
        assert ".env.test" in copied
        assert ".flake8" in copied
        assert (wt / ".env").read_text(encoding="utf-8") == "KEY=1"
        assert (wt / ".env.test").read_text(encoding="utf-8") == "TEST=true"

    def test_stop_agent_success(self) -> None:
        """stop_agent invokes herdr agent stop worker_<task_id>."""
        mock_proc = MagicMock(returncode=0, stdout="agent stopped", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            ok, msg = HerdrDispatcher.stop_agent("t1")
            assert ok is True
            assert msg == "agent stopped"
            mock_run.assert_called_once_with(
                ["herdr", "agent", "stop", "worker_t1"],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_stop_agent_not_found(self) -> None:
        """stop_agent returns error when executable not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            ok, msg = HerdrDispatcher.stop_agent("t1")
            assert ok is False
            assert "not found" in msg

    def test_cleanup_worktree(self) -> None:
        """cleanup_worktree stops agent, sleeps 1s, and runs git worktree remove --force."""
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch.object(
                HerdrDispatcher, "stop_agent", return_value=(True, "stopped")
            ) as mock_stop,
            patch("time.sleep") as mock_sleep,
            patch("subprocess.run", return_value=mock_proc) as mock_run,
        ):
            ok, msg = HerdrDispatcher.cleanup_worktree("t1")
            assert ok is True
            assert "Cleaned up worktree for task t1" in msg
            mock_stop.assert_called_once_with("t1", executable="herdr")
            mock_sleep.assert_called_once_with(1.0)
            mock_run.assert_called_once()
            cmd_called = mock_run.call_args[0][0]
            assert "git" in cmd_called
            assert "worktree" in cmd_called
            assert "remove" in cmd_called
            assert "--force" in cmd_called

    def test_merge_worktree_to_feature_success(self) -> None:
        """merge_worktree_to_feature follows full checkout -> merge -> cleanup -> branch delete."""
        mock_ok = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch.object(HerdrDispatcher, "stop_agent", return_value=(True, "stopped")),
            patch.object(HerdrDispatcher, "cleanup_worktree", return_value=(True, "cleaned")),
            patch("subprocess.run", return_value=mock_ok) as mock_run,
        ):
            ok, msg = HerdrDispatcher.merge_worktree_to_feature(
                task_id="subtask_02", target_branch="feat/test_branch", no_ff=True
            )
            assert ok is True
            assert "Successfully merged agent/subtask_02 into feat/test_branch" in msg
            # Check subprocess calls: checkout, merge, branch -d
            calls = [c[0][0] for c in mock_run.call_args_list]
            assert ["git", "checkout", "feat/test_branch"] in calls
            assert [
                "git",
                "merge",
                "--no-ff",
                "agent/subtask_02",
                "-m",
                "feat(subtask_02): integrate subtask into feat/test_branch",
            ] in calls
            assert ["git", "branch", "-d", "agent/subtask_02"] in calls

    def test_merge_worktree_to_feature_checkout_failure(self) -> None:
        """merge_worktree_to_feature aborts if checkout fails."""
        mock_fail = MagicMock(
            returncode=1, stdout="", stderr="error: pathspec 'feat/foo' did not match"
        )
        with (
            patch.object(HerdrDispatcher, "stop_agent", return_value=(True, "stopped")),
            patch("subprocess.run", return_value=mock_fail),
        ):
            ok, msg = HerdrDispatcher.merge_worktree_to_feature("t1", "feat/foo")
            assert ok is False
            assert "Failed to checkout feat/foo" in msg

    def test_abort_task(self, tmp_path: Path) -> None:
        """abort_task archives diff log, stops agent, cleans up worktree, and deletes branch."""
        mock_diff = MagicMock(returncode=0, stdout="diff --git a/foo b/foo\n", stderr="")
        mock_del = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch.object(
                HerdrDispatcher, "stop_agent", return_value=(True, "stopped")
            ) as mock_stop,
            patch.object(
                HerdrDispatcher, "cleanup_worktree", return_value=(True, "cleaned")
            ) as mock_cleanup,
            patch("subprocess.run", side_effect=[mock_diff, mock_del]),
        ):
            ok, msg = HerdrDispatcher.abort_task(
                task_id="t1", reason="critic rejected 3x", repo_root=tmp_path
            )
            assert ok is True
            assert "Task t1 aborted" in msg
            failures_dir = tmp_path / ".ai" / "failures"
            assert failures_dir.exists()
            log_files = list(failures_dir.glob("t1_*.log"))
            assert len(log_files) == 1
            content = log_files[0].read_text(encoding="utf-8")
            assert "critic rejected 3x" in content
            assert "diff --git" in content
            mock_stop.assert_called_once()
            mock_cleanup.assert_called_once()


class TestLifecycleCliCommands:
    """Test suite for feature, worktree, wait, and abort CLI commands."""

    def test_feature_create_success(self) -> None:
        runner = CliRunner()
        with patch.object(
            HerdrDispatcher,
            "create_feature_branch",
            return_value=(True, "Created and checked out branch 'feat/foo' from 'main'"),
        ):
            result = runner.invoke(main, ["feature", "create", "foo"])
            assert result.exit_code == 0
            assert "Created and checked out branch 'feat/foo'" in result.output

    def test_feature_create_failure(self) -> None:
        runner = CliRunner()
        with patch.object(
            HerdrDispatcher,
            "create_feature_branch",
            return_value=(False, "Working tree is dirty"),
        ):
            result = runner.invoke(main, ["feature", "create", "foo"])
            assert result.exit_code != 0
            assert "Failed to create feature branch: Working tree is dirty" in result.output

    def test_worktree_merge_success(self) -> None:
        runner = CliRunner()
        with patch.object(
            HerdrDispatcher,
            "merge_worktree_to_feature",
            return_value=(True, "Merged successfully"),
        ):
            result = runner.invoke(main, ["worktree", "merge", "t1", "--into", "feat/bar"])
            assert result.exit_code == 0
            assert "Merged successfully" in result.output

    def test_worktree_cleanup_success(self) -> None:
        runner = CliRunner()
        with patch.object(
            HerdrDispatcher,
            "cleanup_worktree",
            return_value=(True, "Cleaned up worktree"),
        ):
            result = runner.invoke(main, ["worktree", "cleanup", "t1"])
            assert result.exit_code == 0
            assert "Cleaned up worktree" in result.output

    def test_wait_cli_success(self) -> None:
        runner = CliRunner()
        with patch.object(
            HerdrDispatcher,
            "wait_for_task",
            return_value=(True, "[WORKER_COMPLETED]"),
        ):
            result = runner.invoke(main, ["wait", "task_01", "--timeout", "10"])
            assert result.exit_code == 0
            assert "Task 'task_01' completed: [WORKER_COMPLETED]" in result.output

    def test_wait_cli_timeout(self) -> None:
        runner = CliRunner()
        with patch.object(
            HerdrDispatcher,
            "wait_for_task",
            return_value=(False, "Task task_01 timed out after 5s"),
        ):
            result = runner.invoke(main, ["wait", "task_01", "--timeout", "5"])
            assert result.exit_code != 0
            assert "Task task_01 timed out after 5s" in result.output

    def test_abort_cli_success(self) -> None:
        runner = CliRunner()
        with patch.object(
            HerdrDispatcher,
            "abort_task",
            return_value=(True, "Task t1 aborted. Log: .ai/failures/t1.log"),
        ):
            result = runner.invoke(main, ["abort", "t1", "--reason", "Timeout"])
            assert result.exit_code == 0
            assert "Task t1 aborted" in result.output

    def test_trust_workspace_creates_file_and_adds_paths(self, tmp_path: Path) -> None:
        """Test trust_workspace when settings.json does not exist yet."""
        settings_file = tmp_path / "settings.json"
        wt_path = tmp_path / "my_project" / ".worktrees" / "agent" / "subtask_01"
        wt_path.mkdir(parents=True, exist_ok=True)

        res = HerdrDispatcher.trust_workspace(wt_path, settings_file=settings_file)
        assert res is True
        assert settings_file.is_file()

        with open(settings_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "trustedWorkspaces" in data
        trusted = data["trustedWorkspaces"]
        assert str(wt_path.resolve()) in trusted
        # Parent .worktrees should also be added
        parent_wt = str((tmp_path / "my_project" / ".worktrees").resolve())
        assert parent_wt in trusted

    def test_trust_workspace_idempotent(self, tmp_path: Path) -> None:
        """Test trust_workspace does not duplicate existing paths."""
        settings_file = tmp_path / "settings.json"
        wt_path = tmp_path / "repo" / "custom"
        wt_path.mkdir(parents=True, exist_ok=True)

        # Prepopulate settings
        settings_file.write_text(
            json.dumps({"trustedWorkspaces": [str(wt_path.resolve())]}),
            encoding="utf-8",
        )

        res = HerdrDispatcher.trust_workspace(wt_path, settings_file=settings_file)
        assert res is True

        with open(settings_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert len(data["trustedWorkspaces"]) == 1
        assert data["trustedWorkspaces"][0] == str(wt_path.resolve())
