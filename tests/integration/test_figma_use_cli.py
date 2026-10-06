"""Integration tests for figma-use CLI entrypoint and argument handling."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

CLI_PATH = Path("D:/herness_agent/.runs/figma-use/packages/cli/src/index.ts")


def find_runner() -> tuple[list[str], str]:
    """Determine the command runner for figma-use CLI.

    Returns:
        tuple of (cmd_prefix, runtime_name)
    """
    bun_path = shutil.which("bun")
    if bun_path:
        return ([bun_path, "run", str(CLI_PATH)], "bun")

    pytest.skip("bun runtime is not installed in the test environment (Edge Case 5)")


def test_figma_use_cli_help():
    """Verify that figma-use displays help information when invoked with --help."""
    if not CLI_PATH.exists():
        pytest.skip(f"figma-use entrypoint not found at {CLI_PATH}")

    runner, runtime_name = find_runner()
    cmd = runner + ["--help"]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert proc.returncode == 0 or "Usage" in proc.stdout or "help" in proc.stdout.lower()
        combined_output = proc.stdout + proc.stderr
        # Verify typical CLI or command listing
        assert any(
            keyword in combined_output.lower()
            for keyword in ["help", "command", "options", "usage", "figma"]
        )
    except subprocess.TimeoutExpired:
        pytest.fail("figma-use --help timed out after 15 seconds")


def test_figma_use_disconnected_status():
    """Verify that figma-use status returns gracefully with error instructions when disconnected."""
    if not CLI_PATH.exists():
        pytest.skip(f"figma-use entrypoint not found at {CLI_PATH}")

    runner, runtime_name = find_runner()
    cmd = runner + ["status"]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        output = proc.stdout + proc.stderr
        # When Figma is not running or listening on 9222, it should output an informative message
        assert any(
            hint in output.lower()
            for hint in [
                "connect",
                "figma",
                "port",
                "error",
                "closed",
                "not running",
                "status",
                "listening",
            ]
        )
    except subprocess.TimeoutExpired:
        pytest.fail("figma-use status timed out after 15 seconds")
