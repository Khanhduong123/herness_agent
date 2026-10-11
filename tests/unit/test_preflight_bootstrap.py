"""Unit tests for pre-flight bootstrap verification and direct system injection."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_agent.core.dispatch import HerdrDispatcher, verify_and_load_agents_rule
from harness_agent.core.models import AgyConfig, Task
from harness_agent.core.runner import AgyRunner, build_cache_aligned_prompt


class TestPreflightBootstrap:
    """Test suite for verify_and_load_agents_rule and prompt injection."""

    def test_tc01_normal_load_succeeds_on_first_attempt(self, tmp_path: Path) -> None:
        """TC-01: Valid directory with AGENTS.md returns content on first attempt."""
        agents_file = tmp_path / "AGENTS.md"
        expected_content = "# AGENTS.md: System Rules and Guidelines\n- Rule 0: Zero tolerance\n"
        agents_file.write_text(expected_content, encoding="utf-8")

        result = verify_and_load_agents_rule(tmp_path)
        assert result == expected_content

        # Also verify through HerdrDispatcher alias
        result_alias = HerdrDispatcher.verify_and_load_agents_rule(tmp_path)
        assert result_alias == expected_content

    def test_tc02_temporary_miss_succeeds_on_retry(self, tmp_path: Path) -> None:
        """TC-02: Temporary miss succeeds on retry 2, retries logged."""
        agents_file = tmp_path / "AGENTS.md"
        expected_content = "# AGENTS.md Content after retry\n"

        call_count = 0
        original_is_file = Path.is_file

        def mock_is_file(self: Path) -> bool:
            nonlocal call_count
            if self.resolve() == agents_file.resolve():
                call_count += 1
                if call_count == 1:
                    return False
                return True
            return original_is_file(self)

        agents_file.write_text(expected_content, encoding="utf-8")

        with patch.object(Path, "is_file", autospec=True, side_effect=mock_is_file):
            with patch("time.sleep") as mock_sleep:
                content = verify_and_load_agents_rule(tmp_path, max_retries=3, base_delay=0.1)
                assert content == expected_content
                assert call_count == 2
                assert mock_sleep.call_count == 1
                mock_sleep.assert_called_with(0.1)

    def test_tc03_file_missing_permanently(self, tmp_path: Path) -> None:
        """TC-03: File missing permanently raises RuntimeError with structured message."""
        non_existent_dir = tmp_path / "non_existent_folder"

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(
                RuntimeError,
                match="Pre-flight bootstrap failed: AGENTS.md not accessible after retries",
            ):
                verify_and_load_agents_rule(non_existent_dir, max_retries=3, base_delay=0.01)
            assert mock_sleep.call_count == 2

    def test_tc04_empty_agents_file(self, tmp_path: Path) -> None:
        """TC-04: Empty (0-byte or whitespace) AGENTS.md raises ValueError."""
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("   \n\t  ", encoding="utf-8")

        with pytest.raises(ValueError, match="AGENTS.md is empty"):
            verify_and_load_agents_rule(tmp_path)

    def test_tc05_filesystem_permission_error(self, tmp_path: Path) -> None:
        """TC-05: PermissionError or OSError during read is caught and raises RuntimeError."""
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("Valid content", encoding="utf-8")

        with patch.object(Path, "read_text", side_effect=PermissionError("Access denied")):
            with patch("time.sleep") as mock_sleep:
                with pytest.raises(
                    RuntimeError,
                    match="Pre-flight bootstrap failed: AGENTS.md not accessible after retries",
                ):
                    verify_and_load_agents_rule(tmp_path, max_retries=3, base_delay=0.05)
                assert mock_sleep.call_count == 2

    def test_tc06_path_as_string_and_path_object(self, tmp_path: Path) -> None:
        """TC-06: Path can be passed as both str and pathlib.Path."""
        agents_file = tmp_path / "AGENTS.md"
        expected = "# Guidelines\n"
        agents_file.write_text(expected, encoding="utf-8")

        # String path
        res_str = verify_and_load_agents_rule(str(tmp_path))
        assert res_str == expected

        # Path object
        res_path = verify_and_load_agents_rule(tmp_path)
        assert res_path == expected

    def test_tc07_build_cache_aligned_prompt_injection(self, tmp_path: Path) -> None:
        """TC-07: build_cache_aligned_prompt injects AGENTS.md when inject_agents_rule=True."""
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("RULE: Do not write root code", encoding="utf-8")

        static_prefix, dynamic_tail = build_cache_aligned_prompt(
            system_instructions="Role guidance",
            dynamic_context={"task": "01"},
            user_prompt="Run checks",
            inject_agents_rule=True,
            root_path=tmp_path,
        )

        assert "RULE: Do not write root code" in static_prefix
        assert "Role guidance" in static_prefix
        assert "DO NOT output decorative emojis" in static_prefix
        assert "Run checks" in dynamic_tail

    def test_tc08_herdr_dispatch_start_agent_injection(self, tmp_path: Path) -> None:
        """TC-08: HerdrDispatcher.start_agent with inject_agents_rule injects into prompt file."""
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("SYSTEM RULE: Strict worktree isolation", encoding="utf-8")

        prompt_file = tmp_path / "worker_prompt.md"
        prompt_file.write_text("Task instructions", encoding="utf-8")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="agent started", stderr="")
            ok, msg = HerdrDispatcher.start_agent(
                task_id="test_task",
                pane_id="pane_1",
                system_prompt_file=str(prompt_file),
                inject_agents_rule=True,
                repo_root=tmp_path,
            )
            assert ok is True
            # Check prompt file content has injected AGENTS.md rule
            updated_content = prompt_file.read_text(encoding="utf-8")
            assert "SYSTEM RULE: Strict worktree isolation" in updated_content
            assert "Task instructions" in updated_content

    def test_tc09_herdr_dispatch_prompt_agent_injection(self, tmp_path: Path) -> None:
        """TC-09: HerdrDispatcher.prompt_agent with inject_agents_rule prepends rule."""
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("MANDATORY RULE", encoding="utf-8")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="prompted", stderr="")
            ok, msg = HerdrDispatcher.prompt_agent(
                task_id="test_task",
                prompt="Do work",
                inject_agents_rule=True,
                repo_root=tmp_path,
            )
            assert ok is True
            # Verify command sent to subprocess
            call_cmd = mock_run.call_args[0][0]
            prompt_arg = call_cmd[-1]
            assert "MANDATORY RULE" in prompt_arg
            assert "Do work" in prompt_arg

    @pytest.mark.asyncio
    async def test_tc10_runner_execute_task_injection(self, tmp_path: Path) -> None:
        """TC-10: AgyRunner.execute_task prepends verified AGENTS.md when enabled."""
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("INJECTED_AGENTS_RULE", encoding="utf-8")

        runner = AgyRunner(config=AgyConfig(executable_path="agy", auto_log=False))
        task = Task(id="t1", name="Test Task", prompt="Execute subtask")

        captured_args = []

        class DummyProcess:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return b'{"done": true}\n', b""

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured_args.extend(args)
            return DummyProcess()

        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            res = await runner.execute_task(
                task=task,
                inject_agents_rule=True,
                repo_root=tmp_path,
            )
            assert res.success is True
            # Inspect command passed to subprocess
            print_idx = captured_args.index("--print")
            dispatched_prompt = captured_args[print_idx + 1]
            assert "INJECTED_AGENTS_RULE" in dispatched_prompt
            assert "Execute subtask" in dispatched_prompt
