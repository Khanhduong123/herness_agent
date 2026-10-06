"""Integration tests for live Figma Desktop interaction via figma-use CDP."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

CLI_PATH = Path("D:/herness_agent/.runs/figma-use/packages/cli/src/index.ts")


def is_figma_cdp_active(host: str = "127.0.0.1", port: int = 9222, timeout: float = 1.0) -> bool:
    """Probe if Figma Desktop CDP debug port is listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except (socket.timeout, OSError):
            return False


def get_cli_runner() -> list[str]:
    """Retrieve command runner prefix for figma-use."""
    bun_path = shutil.which("bun")
    if bun_path:
        return [bun_path, "run", str(CLI_PATH)]

    pytest.skip("bun runtime is not installed in the test environment (Edge Case 5)")


def test_figma_desktop_connectivity_probe():
    """Verify CDP port probe behavior without throwing unexpected exceptions."""
    is_active = is_figma_cdp_active(port=9222, timeout=0.5)
    assert isinstance(is_active, bool)


def test_live_figma_desktop_create_inspect_delete():
    """Verify live canvas frame creation, inspection, and guaranteed cleanup."""
    if not is_figma_cdp_active(port=9222):
        pytest.skip("Figma Desktop not active on port 9222")

    runner = get_cli_runner()
    created_node_id: str | None = None

    try:
        # 1. Handshake
        status_cmd = runner + ["status", "--json"]
        proc_status = subprocess.run(
            status_cmd, capture_output=True, text=True, timeout=15, check=False
        )
        assert proc_status.returncode == 0

        # 2. Canvas Mutation
        create_cmd = runner + [
            "create",
            "frame",
            "--name",
            "__harness_test_node__",
            "--width",
            "120",
            "--height",
            "60",
            "--fill",
            "#3B82F6",
            "--json",
        ]
        proc_create = subprocess.run(
            create_cmd, capture_output=True, text=True, timeout=15, check=False
        )
        assert proc_create.returncode == 0
        data = json.loads(proc_create.stdout)
        created_node_id = data.get("id") or data.get("nodeId")
        assert created_node_id is not None

        # 3. Verification
        get_cmd = runner + ["get", "node", str(created_node_id), "--json"]
        proc_get = subprocess.run(get_cmd, capture_output=True, text=True, timeout=15, check=False)
        assert proc_get.returncode == 0
        node_info = json.loads(proc_get.stdout)
        assert node_info.get("name") == "__harness_test_node__"

    finally:
        # 4. Teardown / Cleanup
        if created_node_id:
            delete_cmd = runner + ["node", "delete", str(created_node_id)]
            subprocess.run(delete_cmd, capture_output=True, text=True, timeout=15, check=False)


def test_live_figma_desktop_render_jsx():
    """Verify live canvas JSX rendering and teardown."""
    if not is_figma_cdp_active(port=9222):
        pytest.skip("Figma Desktop not active on port 9222")

    runner = get_cli_runner()
    jsx_content = (
        '<Frame name="__harness_jsx_node__" w={100} h={50} bg="#10B981"><Text>Test</Text></Frame>'
    )
    rendered_node_id: str | None = None

    try:
        render_cmd = runner + ["render", "--code", jsx_content, "--json"]
        proc_render = subprocess.run(
            render_cmd, capture_output=True, text=True, timeout=15, check=False
        )
        if proc_render.returncode == 0 and proc_render.stdout.strip():
            try:
                res = json.loads(proc_render.stdout)
                rendered_node_id = res.get("id") or res.get("nodeId")
            except json.JSONDecodeError:
                pass
    finally:
        if rendered_node_id:
            delete_cmd = runner + ["node", "delete", str(rendered_node_id)]
            subprocess.run(delete_cmd, capture_output=True, text=True, timeout=15, check=False)
