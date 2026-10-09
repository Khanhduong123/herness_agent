"""Unit tests for sliding-window history compression and micro-summary."""

from harness_agent.core.state import compress_history


def test_compress_history_empty_events() -> None:
    """Empty events return empty summary and empty recent active list."""
    summary, active = compress_history([], window_size=5)
    assert summary == ""
    assert active == []


def test_compress_history_less_than_window_size() -> None:
    """TC-01: History <= window_size returns empty summary and intact events."""
    events = [
        {"role": "user", "content": "Initial prompt"},
        {"role": "assistant", "action": "Analyzing directory"},
        {"role": "tool", "tool": "view_file", "output": "File contents"},
    ]
    summary, active = compress_history(events, window_size=5)
    assert summary == ""
    assert active == events
    assert len(active) == 3


def test_compress_history_exact_window_size() -> None:
    """History exactly equal to window_size returns empty summary and intact events."""
    events = [{"id": i} for i in range(5)]
    summary, active = compress_history(events, window_size=5)
    assert summary == ""
    assert active == events


def test_compress_history_greater_than_window_size() -> None:
    """TC-02: History larger than window_size summarizes older turns and preserves active window."""
    events = [
        {
            "tool_calls": [{"name": "view_file", "args": {"TargetFile": "src/main.py"}}],
            "status": "success",
            "output": "Found entrypoint function",
        },
        {
            "tool_calls": [{"name": "run_command", "args": {"CommandLine": "pytest"}}],
            "returncode": 1,
            "output": "1 test failed in test_auth.py",
        },
        {
            "action": "Investigating test error",
            "decision": "Need to patch auth header parsing",
        },
        {
            "tool_calls": [{"name": "replace_file_content", "args": {"TargetFile": "src/auth.py"}}],
            "status": "success",
            "output": "Successfully patched line 42",
        },
        {
            "tool_calls": [{"name": "run_command", "args": {"CommandLine": "pytest"}}],
            "returncode": 0,
            "output": "All tests passed",
        },
        {"role": "assistant", "content": "Recent turn 1"},
        {"role": "assistant", "content": "Recent turn 2"},
        {"role": "assistant", "content": "Recent turn 3"},
    ]

    # 8 total turns, window_size=3 -> 5 older turns summarized, 3 active turns
    summary, active = compress_history(events, window_size=3)

    assert len(active) == 3
    assert active == events[5:]
    assert "### Execution History Summary" in summary
    assert "view_file(src/main.py)" in summary
    assert "replace_file_content(src/auth.py)" in summary
    assert "failure (code 1)" in summary
    assert "All tests passed" in summary


def test_compress_history_fault_tolerant_and_deduplication() -> None:
    """TC-03: Fault-tolerant parsing of missing/malformed fields and repeated failures."""
    events = [
        # Missing fields entirely
        {},
        # Malformed / empty tool calls
        {"tool_calls": None},
        # Repeated identical failures
        {
            "tool_calls": [{"name": "run_command", "args": {"CommandLine": "make build"}}],
            "status": "failed",
            "output": "Compilation error",
        },
        {
            "tool_calls": [{"name": "run_command", "args": {"CommandLine": "make build"}}],
            "status": "failed",
            "output": "Compilation error",
        },
        {
            "tool_calls": [{"name": "run_command", "args": {"CommandLine": "make build"}}],
            "status": "failed",
            "output": "Compilation error",
        },
        # Active window events
        {"role": "assistant", "content": "Recovery step"},
    ]

    summary, active = compress_history(events, window_size=1)

    assert len(active) == 1
    assert active[0]["content"] == "Recovery step"
    assert "run_command" in summary
    assert "repeated 3x" in summary
    assert "Compilation error" in summary
