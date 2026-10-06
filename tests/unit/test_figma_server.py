"""Unit tests for FigmaMCPServer."""

import json
from unittest.mock import MagicMock

from harness_agent.figma.models import FigmaAssetExport
from harness_agent.figma.server import FigmaMCPServer


def test_mcp_server_tools_list_schema():
    server = FigmaMCPServer()
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    resp = server.handle_message(msg)

    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "get_frame_layout" in tool_names
    assert "get_design_tokens" in tool_names
    assert "export_node_image" in tool_names


def test_mcp_server_export_node_image_returns_local_path():
    mock_client = MagicMock()
    mock_client.parse_figma_url.return_value = ("fileKey123", "10:20")
    mock_client.export_node_image.return_value = FigmaAssetExport(
        node_id="10:20",
        local_path="assets/images/10_20.png",
        format="png",
        file_size_bytes=4096,
    )

    server = FigmaMCPServer(client=mock_client)
    msg = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "export_node_image",
            "arguments": {
                "url_or_key": "https://www.figma.com/file/fileKey123/Test?node-id=10-20",
                "node_id": "10:20",
            },
        },
    }
    resp = server.handle_message(msg)

    assert resp["id"] == 2
    assert "result" in resp
    content = resp["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"
    data = json.loads(content[0]["text"])
    assert data["local_path"] == "assets/images/10_20.png"
    assert data["file_size_bytes"] == 4096


def test_mcp_server_tool_dispatch():
    mock_client = MagicMock()
    mock_client.parse_figma_url.return_value = ("key123", None)
    mock_client.get_file.return_value = {
        "document": {
            "id": "0:0",
            "name": "Root",
            "type": "DOCUMENT",
            "children": [],
        }
    }

    server = FigmaMCPServer(client=mock_client)

    # 1. get_frame_layout
    msg_layout = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "get_frame_layout",
            "arguments": {"url_or_key": "key123"},
        },
    }
    resp_layout = server.handle_message(msg_layout)
    assert resp_layout["id"] == 10
    layout_data = json.loads(resp_layout["result"]["content"][0]["text"])
    assert layout_data["id"] == "0:0"

    # 2. get_design_tokens
    msg_tokens = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "get_design_tokens",
            "arguments": {"url_or_key": "key123"},
        },
    }
    resp_tokens = server.handle_message(msg_tokens)
    assert resp_tokens["id"] == 11
    tokens_data = json.loads(resp_tokens["result"]["content"][0]["text"])
    assert "colors" in tokens_data

    # 3. Invalid tool
    msg_invalid = {
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {"name": "non_existent_tool", "arguments": {}},
    }
    resp_invalid = server.handle_message(msg_invalid)
    assert "error" in resp_invalid
    assert resp_invalid["error"]["code"] == -32000
