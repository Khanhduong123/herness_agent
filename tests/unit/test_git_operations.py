"""Unit tests for headless git command execution and safety wrapper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_agent.core.pr import _redact_secrets, safe_run_git_command


def test_redact_secrets() -> None:
    """Verifies sensitive tokens are redacted from text strings."""
    assert _redact_secrets("") == ""
    assert _redact_secrets("Normal text without tokens") == "Normal text without tokens"

    # GitHub Personal Access Token
    raw_ghp = "fatal: Authentication failed for 'https://ghp_1234567890abcdef@github.com'"
    redacted_ghp = _redact_secrets(raw_ghp)
    assert "ghp_1234567890abcdef" not in redacted_ghp
    assert "[REDACTED_SECRET]" in redacted_ghp

    # Bearer Token
    raw_bearer = "Authorization: Bearer secret_jwt_token_12345-abc_xyz"
    redacted_bearer = _redact_secrets(raw_bearer)
    assert "secret_jwt_token_12345-abc_xyz" not in redacted_bearer
    assert "Bearer [REDACTED_SECRET]" in redacted_bearer


def test_safe_run_git_command_normal_execution() -> None:
    """TC-01: Verifies normal git command execution returns CompletedProcess."""
    res = safe_run_git_command(["--version"], timeout=10.0)
    assert isinstance(res, subprocess.CompletedProcess)
    assert res.returncode == 0
    assert "git version" in res.stdout.lower()


def test_safe_run_git_command_invalid_cwd(tmp_path: Path) -> None:
    """Verifies ValueError is raised when cwd does not exist."""
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(ValueError, match="Working directory does not exist"):
        safe_run_git_command(["status"], cwd=non_existent)


def test_safe_run_git_command_headless_env_vars() -> None:
    """TC-02: Verifies headless environment variables are injected into subprocess."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "status"],
            returncode=0,
            stdout="clean",
            stderr="",
        )

        safe_run_git_command(["status"])

        assert mock_run.called
        call_kwargs = mock_run.call_args[1]
        env = call_kwargs.get("env", {})
        assert env.get("GIT_TERMINAL_PROMPT") == "0"
        assert env.get("GIT_SSH_COMMAND") == "ssh -o BatchMode=yes"


def test_safe_run_git_command_github_token_fallback() -> None:
    """Verifies GITHUB_TOKEN and GH_TOKEN synchronization fallback."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "token_123"}, clear=True):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "status"],
                returncode=0,
                stdout="",
                stderr="",
            )
            safe_run_git_command(["status"])
            call_kwargs = mock_run.call_args[1]
            env = call_kwargs.get("env", {})
            assert env.get("GH_TOKEN") == "token_123"

    with patch.dict(os.environ, {"GH_TOKEN": "token_456"}, clear=True):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "status"],
                returncode=0,
                stdout="",
                stderr="",
            )
            safe_run_git_command(["status"])
            call_kwargs = mock_run.call_args[1]
            env = call_kwargs.get("env", {})
            assert env.get("GITHUB_TOKEN") == "token_456"


def test_safe_run_git_command_timeout(tmp_path: Path) -> None:
    """TC-03: Verifies command exceeding timeout raises TimeoutExpired and logs error."""
    log_file = tmp_path / "test_git_diagnostics.log"

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["git", "fetch"],
            timeout=1.0,
            stderr="fatal: connection timed out",
        )

        with pytest.raises(subprocess.TimeoutExpired):
            safe_run_git_command(["fetch"], timeout=1.0, log_path=log_file)

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Command: git fetch" in content
    assert "TimeoutExpired" in content
    assert "fatal: connection timed out" in content


def test_safe_run_git_command_called_process_error_and_secret_redaction(tmp_path: Path) -> None:
    """TC-04: Verifies non-zero exit raises CalledProcessError and masks sensitive tokens in log."""
    log_file = tmp_path / "test_git_diagnostics.log"

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "push"],
            stderr="fatal: remote rejected with token ghp_1234567890abcdef and Bearer secret_123",
        )

        with pytest.raises(subprocess.CalledProcessError):
            safe_run_git_command(["push"], log_path=log_file)

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Command: git push" in content
    assert "CalledProcessError" in content
    assert "ghp_1234567890abcdef" not in content
    assert "secret_123" not in content
    assert "[REDACTED_SECRET]" in content
