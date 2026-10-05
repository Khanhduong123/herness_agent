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
    repo_root = Path(__file__).resolve().parent.parent
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
    expected_cmd = "python src/harness_agent/hooks/enforce_orchestrator.py"
    assert handler.get("command") == expected_cmd


def test_subprocess_hook_execution() -> None:
    """Test executing the hook script directly via Python subprocess."""
    repo_root = Path(__file__).resolve().parent.parent
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
