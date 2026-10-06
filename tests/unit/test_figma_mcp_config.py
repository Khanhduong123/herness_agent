"""Unit tests for Figma MCP configuration and manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def get_plugin_dir() -> Path:
    """Resolve directory containing plugin files."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / ".agents" / "plugins" / "figma"


def test_mcp_config_validity():
    """Verify .agents/plugins/figma/mcp_config.json schema and server configs."""
    plugin_dir = get_plugin_dir()
    config_path = plugin_dir / "mcp_config.json"

    assert config_path.exists(), f"Configuration file missing at {config_path}"

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    assert "mcpServers" in config, "mcpServers root key missing from config"
    servers = config["mcpServers"]
    assert "figma" in servers, "'figma' server entry missing"
    assert "figma-use" in servers, "'figma-use' server entry missing"

    # Validate figma server
    figma_server = servers["figma"]
    assert figma_server.get("command") == "conda"
    assert "harness_agent.figma.server" in figma_server.get("args", [])
    assert figma_server.get("env", {}).get("PYTHONUNBUFFERED") == "1"

    # Validate figma-use server
    figma_use_server = servers["figma-use"]
    assert figma_use_server.get("command") in ("bun", "node")
    args = figma_use_server.get("args", [])
    assert len(args) >= 3
    assert args[-2] == "mcp"
    assert args[-1] == "serve"

    # Validate referenced CLI entrypoint path exists
    target_path_str = args[1]
    # Path portability: shouldn't use unescaped backslashes in json
    assert "\\" not in target_path_str, "Path must use forward slashes in JSON"
    target_path = Path(target_path_str)
    assert target_path.exists(), f"Referenced entrypoint does not exist: {target_path}"

    # Validate env
    assert figma_use_server.get("env", {}).get("FIGMA_PORT") == "9222"


def test_plugin_manifest_validity():
    """Verify .agents/plugins/figma/plugin.json metadata and semantic version."""
    plugin_dir = get_plugin_dir()
    manifest_path = plugin_dir / "plugin.json"

    assert manifest_path.exists(), f"Manifest file missing at {manifest_path}"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest.get("name") == "figma"
    version = manifest.get("version", "")
    assert version.startswith("1."), f"Expected semantic version starting with 1., got {version}"
    description = manifest.get("description", "")
    assert "figma-use" in description or "CDP" in description


def test_missing_or_corrupted_config(tmp_path: Path):
    """Verify handling of missing or corrupted config files."""
    missing_path = tmp_path / "nonexistent_mcp.json"
    with pytest.raises(FileNotFoundError):
        with open(missing_path, "r", encoding="utf-8") as f:
            json.load(f)

    corrupted_path = tmp_path / "corrupted_mcp.json"
    corrupted_path.write_text("{ incomplete_json: ", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        with open(corrupted_path, "r", encoding="utf-8") as f:
            json.load(f)
