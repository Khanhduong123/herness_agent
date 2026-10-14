"""Tests for lifecycle hooks and Orchestrator RULE 0 enforcement."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from harness_agent.hooks.enforce_orchestrator import (
    ORCHESTRATOR_RULE_0_REMINDER,
    EphemeralStep,
    PreInvocationOutput,
    build_preinvocation_payload,
    get_rule_0_reminder,
    main,
)


def test_schema_serialization() -> None:
    """Test that PreInvocationOutput and EphemeralStep serialize correctly."""
    step = EphemeralStep(ephemeralMessage="Test message")
    output = PreInvocationOutput(injectSteps=[step])
    data = output.model_dump()

    assert "injectSteps" in data
    assert len(data["injectSteps"]) == 1
    assert data["injectSteps"][0]["ephemeralMessage"] == "Test message"


def test_get_rule_0_reminder() -> None:
    """Test that RULE 0 reminder string contains essential constraints."""
    reminder = get_rule_0_reminder()
    assert reminder == ORCHESTRATOR_RULE_0_REMINDER
    assert "CRITICAL REMINDER (RULE 0" in reminder
    assert "ZERO-TOLERANCE CODE-WRITING LOCK FOR ORCHESTRATOR" in reminder
    assert "STRICTLY PROHIBITED FROM DIRECTLY WRITING" in reminder
    assert "replace_file_content" in reminder
    assert "Coder Worker Agent" in reminder
    assert "invoke_subagent" in reminder
    assert "define_subagent" in reminder
    assert "agents ngầm" in reminder
    assert "--dangerously-skip-permissions" in reminder


def test_build_preinvocation_payload_default() -> None:
    """Test building default payload."""
    payload = build_preinvocation_payload()
    assert len(payload.injectSteps) == 1
    assert payload.injectSteps[0].ephemeralMessage == ORCHESTRATOR_RULE_0_REMINDER


def test_build_preinvocation_payload_custom() -> None:
    """Test building payload with custom message."""
    custom_msg = "Custom ephemeral alert"
    payload = build_preinvocation_payload(message=custom_msg)
    assert len(payload.injectSteps) == 1
    assert payload.injectSteps[0].ephemeralMessage == custom_msg


def test_main_with_valid_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test main function execution with mock valid stdin JSON."""
    input_payload: Dict[str, Any] = {
        "conversationId": "test-uuid-1234",
        "invocationNum": 1,
        "workspacePaths": ["/test/workspace"],
    }
    stdin_stream = io.StringIO(json.dumps(input_payload))
    stdout_stream = io.StringIO()

    monkeypatch.setattr(sys, "stdin", stdin_stream)
    monkeypatch.setattr(sys, "stdout", stdout_stream)
    # Ensure isatty returns False so stdin is read
    monkeypatch.setattr(stdin_stream, "isatty", lambda: False)

    main()

    stdout_val = stdout_stream.getvalue()
    parsed = json.loads(stdout_val)
    assert "injectSteps" in parsed
    assert len(parsed["injectSteps"]) == 1
    assert "RULE 0" in parsed["injectSteps"][0]["ephemeralMessage"]


def test_main_with_malformed_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test main function resilience when stdin receives malformed JSON."""
    stdin_stream = io.StringIO("invalid json content")
    stdout_stream = io.StringIO()

    monkeypatch.setattr(sys, "stdin", stdin_stream)
    monkeypatch.setattr(sys, "stdout", stdout_stream)
    monkeypatch.setattr(stdin_stream, "isatty", lambda: False)

    # Should not raise exception
    main()

    stdout_val = stdout_stream.getvalue()
    parsed = json.loads(stdout_val)
    assert "injectSteps" in parsed
    assert len(parsed["injectSteps"]) == 1


def test_hooks_json_registration() -> None:
    """Verify that .agents/hooks.json exists and registers the hook."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    hooks_file = repo_root / ".agents" / "hooks.json"

    assert hooks_file.exists(), f"Missing hooks config at {hooks_file}"

    with open(hooks_file, "r", encoding="utf-8") as f:
        hooks_config = json.load(f)

    assert "enforce-orchestrator-role" in hooks_config
    role_hook = hooks_config["enforce-orchestrator-role"]
    assert "PreInvocation" in role_hook
    assert isinstance(role_hook["PreInvocation"], list)
    assert len(role_hook["PreInvocation"]) == 1

    handler = role_hook["PreInvocation"][0]
    assert handler.get("type") == "command"
    expected_cmd = "python .agents/hooks/enforce_orchestrator.py"
    assert handler.get("command") == expected_cmd


def test_subprocess_hook_execution() -> None:
    """Test executing the hook script directly via Python subprocess."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    script_path = repo_root / ".agents" / "hooks" / "enforce_orchestrator.py"
    if not script_path.exists():
        script_path = repo_root / "src" / "harness_agent" / "hooks" / "enforce_orchestrator.py"

    assert script_path.exists(), f"Hook script does not exist at {script_path}"

    test_input = json.dumps({"conversationId": "test-subproc-id"}).encode()
    result = subprocess.run(
        [sys.executable, str(script_path)],
        input=test_input,
        capture_output=True,
        cwd=str(repo_root),
        check=True,
    )

    assert result.returncode == 0
    output_json = json.loads(result.stdout.decode("utf-8"))
    assert "injectSteps" in output_json
    assert len(output_json["injectSteps"]) == 1
    assert "RULE 0" in output_json["injectSteps"][0]["ephemeralMessage"]


def test_empty_stdin_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that when sys.stdin is an empty io.StringIO(''), main() executes without error."""
    stdin_stream = io.StringIO("")
    stdout_stream = io.StringIO()

    monkeypatch.setattr(sys, "stdin", stdin_stream)
    monkeypatch.setattr(sys, "stdout", stdout_stream)
    monkeypatch.setattr(stdin_stream, "isatty", lambda: False)

    main()

    stdout_val = stdout_stream.getvalue()
    parsed = json.loads(stdout_val)
    assert "injectSteps" in parsed
    assert len(parsed["injectSteps"]) == 1
    assert "RULE 0" in parsed["injectSteps"][0]["ephemeralMessage"]


def test_hook_script_sync() -> None:
    """Assert that .agents/hooks/enforce_orchestrator.py and src hook have identical contents."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    agents_hook = repo_root / ".agents" / "hooks" / "enforce_orchestrator.py"
    src_hook = repo_root / "src" / "harness_agent" / "hooks" / "enforce_orchestrator.py"

    assert agents_hook.exists(), f"Missing hook at {agents_hook}"
    assert src_hook.exists(), f"Missing hook at {src_hook}"

    assert (
        agents_hook.read_bytes() == src_hook.read_bytes()
    ), f"File content mismatch between {agents_hook} and {src_hook}"


def test_agents_md_size_limit() -> None:
    """Assert that AGENTS.md file size is strictly less than 18,000 bytes."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    agents_md = repo_root / "AGENTS.md"

    assert agents_md.exists(), f"Missing AGENTS.md at {agents_md}"
    size = agents_md.stat().st_size
    assert size < 18000, f"AGENTS.md exceeds 18000 bytes (current: {size} bytes)"


def test_no_undefined_cli_flags_in_docs() -> None:
    """Search AGENTS.md and herdr-cli SKILL.md for undefined flags; assert 0 occurrences."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    agents_md = repo_root / "AGENTS.md"
    herdr_skill = repo_root / ".agents" / "skills" / "herdr-cli" / "SKILL.md"

    forbidden_flags = ["--system-prompt-file", "--thinking-level"]
    files_to_check = [agents_md, herdr_skill]

    for file_path in files_to_check:
        assert file_path.exists(), f"File does not exist: {file_path}"
        content = file_path.read_text(encoding="utf-8")
        for flag in forbidden_flags:
            assert flag not in content, f"Found undefined flag '{flag}' in {file_path}"


def test_subprocess_windows_encoding_safety() -> None:
    """Run hook script in subprocess with PYTHONIOENCODING=cp1252 to verify encoding resilience."""
    import os

    repo_root = Path(__file__).resolve().parent.parent.parent
    script_path = repo_root / ".agents" / "hooks" / "enforce_orchestrator.py"
    if not script_path.exists():
        script_path = repo_root / "src" / "harness_agent" / "hooks" / "enforce_orchestrator.py"

    assert script_path.exists(), f"Hook script does not exist at {script_path}"

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252:replace"

    result = subprocess.run(
        [sys.executable, str(script_path)],
        input=b"",
        capture_output=True,
        cwd=str(repo_root),
        env=env,
        check=True,
    )

    assert result.returncode == 0
    output_str = result.stdout.decode("utf-8")
    output_json = json.loads(output_str)
    assert "injectSteps" in output_json
    assert len(output_json["injectSteps"]) == 1
    # Verify presence of UTF-8 emoji or text
    assert "CRITICAL REMINDER" in output_json["injectSteps"][0]["ephemeralMessage"]
