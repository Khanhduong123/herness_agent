import pytest

from harness_agent.core.models import AgyConfig, Task
from harness_agent.core.runner import AgyRunner


def test_build_command():
    config = AgyConfig(
        executable_path="agy",
        model="gemini-2.5-pro",
        effort="high",
        dangerously_skip_permissions=True,
        timeout_seconds=60,
    )
    runner = AgyRunner(config=config)
    task = Task(id="t1", name="Prompt Test", prompt="Hello agy")

    cmd = runner.build_command(prompt=task.prompt, task=task)
    assert "agy" in cmd[0]
    assert "--print" in cmd
    assert "Hello agy" in cmd
    assert "--model" in cmd
    assert "gemini-2.5-pro" in cmd
    assert "--effort" in cmd
    assert "high" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert "--print-timeout" in cmd
    assert "60s" in cmd


def test_extract_stream_data():
    runner = AgyRunner()
    text_pieces = []
    tool_calls = []

    # Test text event
    runner._extract_stream_data({"type": "text", "text": "foo"}, text_pieces, tool_calls)
    assert text_pieces == ["foo"]

    # Test tool_call event
    runner._extract_stream_data(
        {"type": "tool_call", "name": "run_command", "args": {"cmd": "ls"}},
        text_pieces,
        tool_calls,
    )
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "run_command"
    assert tool_calls[0].args == {"cmd": "ls"}


@pytest.mark.asyncio
async def test_runner_log_run_suppression(tmp_path, monkeypatch):
    """TC-03: execute_task(task, log_run=False) suppresses writing to log.csv."""
    custom_csv = tmp_path / "suppressed_log.csv"
    from harness_agent.core.token_logger import TokenLogger

    monkeypatch.setattr(TokenLogger, "DEFAULT_CSV_PATH", custom_csv)

    runner = AgyRunner(config=AgyConfig(model="gemini-1.5-flash", auto_log=True))
    task = Task(id="t_suppressed", name="Suppressed Task", prompt="Test suppression")

    class DummyProcess:
        returncode = 0

        async def communicate(self):
            return b'{"type": "usage", "prompt_tokens": 100, "completion_tokens": 50}\n', b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        return DummyProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    result = await runner.execute_task(task, log_run=False)
    assert result.success is True
    assert not custom_csv.exists()
