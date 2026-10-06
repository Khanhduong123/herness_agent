"""Unit tests for AgyRunner."""

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
