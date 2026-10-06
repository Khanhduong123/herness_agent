"""Integration tests for the Figma design-to-code pipeline."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from harness_agent.figma.client import FigmaClient
from harness_agent.figma.models import FigmaColor
from harness_agent.figma.server import FigmaMCPServer


def test_end_to_end_figma_url_to_layout_extraction():
    url = "https://www.figma.com/design/testFile123/Dashboard-App?node-id=4-50"

    mock_client = MagicMock(spec=FigmaClient)
    mock_client.parse_figma_url.return_value = ("testFile123", "4:50")

    mock_client.get_file_nodes.return_value = {
        "nodes": {
            "4:50": {
                "document": {
                    "id": "4:50",
                    "name": "NavigationCard",
                    "type": "FRAME",
                    "layoutMode": "HORIZONTAL",
                    "primaryAxisAlignItems": "CENTER",
                    "counterAxisAlignItems": "SPACE_BETWEEN",
                    "paddingTop": 20.0,
                    "paddingRight": 32.0,
                    "paddingBottom": 20.0,
                    "paddingLeft": 32.0,
                    "itemSpacing": 16.0,
                    "layoutGrow": 1.0,
                    "layoutAlign": "STRETCH",
                    "absoluteBoundingBox": {"width": 800.0, "height": 72.0},
                    "children": [
                        {
                            "id": "4:51",
                            "name": "Logo",
                            "type": "FRAME",
                            "layoutMode": "NONE",
                            "itemSpacing": 0.0,
                            "children": [],
                        }
                    ],
                }
            }
        }
    }

    server = FigmaMCPServer(client=mock_client)
    res = server.call_tool("get_frame_layout", {"url_or_key": url})

    assert "content" in res
    text_content = res["content"][0]["text"]
    layout_data = json.loads(text_content)

    assert layout_data["id"] == "4:50"
    assert layout_data["name"] == "NavigationCard"
    assert layout_data["layout_mode"] == "HORIZONTAL"
    assert layout_data["primary_axis_align"] == "CENTER"
    assert layout_data["counter_axis_align"] == "SPACE_BETWEEN"
    assert layout_data["padding"] == {"top": 20.0, "right": 32.0, "bottom": 20.0, "left": 32.0}
    assert layout_data["item_spacing"] == 16.0
    assert layout_data["width"] == 800.0
    assert layout_data["height"] == 72.0
    assert len(layout_data["children"]) == 1
    assert layout_data["children"][0]["id"] == "4:51"


def test_end_to_end_design_tokens_and_color_space_normalization():
    # Test FigmaColor normalization boundary values
    pure_blue = FigmaColor(r=0.1, g=0.5, b=0.9, a=1.0)
    assert pure_blue.hex == "#1A80E6"
    assert pure_blue.rgba_css == "rgba(26, 128, 230, 1.00)"

    semi_trans = FigmaColor(r=0.0, g=1.0, b=0.0, a=0.5)
    assert semi_trans.hex == "#00FF0080"
    assert semi_trans.rgba_css == "rgba(0, 255, 0, 0.50)"

    mock_client = MagicMock(spec=FigmaClient)
    mock_client.parse_figma_url.return_value = ("fileABC", "1:100")
    mock_client.get_file_nodes.return_value = {
        "nodes": {
            "1:100": {
                "document": {
                    "id": "1:100",
                    "name": "PrimaryButton",
                    "type": "FRAME",
                    "cornerRadius": 8.0,
                    "fills": [
                        {
                            "type": "SOLID",
                            "color": {"r": 0.1, "g": 0.5, "b": 0.9, "a": 1.0},
                            "opacity": 1.0,
                        }
                    ],
                    "effects": [
                        {
                            "type": "DROP_SHADOW",
                            "visible": True,
                            "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.15},
                            "offset": {"x": 0.0, "y": 2.0},
                            "radius": 4.0,
                        }
                    ],
                    "children": [
                        {
                            "id": "1:101",
                            "name": "ButtonLabel",
                            "type": "TEXT",
                            "style": {
                                "fontFamily": "Inter",
                                "fontSize": 16.0,
                                "fontWeight": 600,
                                "lineHeightPx": 24.0,
                                "textAlignHorizontal": "CENTER",
                            },
                        }
                    ],
                }
            }
        }
    }

    server = FigmaMCPServer(client=mock_client)
    res = server.call_tool(
        "get_design_tokens",
        {"url_or_key": "https://figma.com/file/fileABC?node-id=1-100"},
    )
    tokens_data = json.loads(res["content"][0]["text"])

    # Color tokens
    assert len(tokens_data["colors"]) == 1
    assert tokens_data["colors"][0]["hex"] == "#1A80E6"
    assert tokens_data["colors"][0]["rgba"] == "rgba(26, 128, 230, 1.00)"

    # Radius tokens
    assert len(tokens_data["radius"]) == 1
    assert tokens_data["radius"][0]["corner_radius"] == 8.0

    # Typography tokens
    assert len(tokens_data["typography"]) == 1
    typo = tokens_data["typography"][0]
    assert typo["font_family"] == "Inter"
    assert typo["font_size"] == 16.0
    assert typo["font_weight"] == 600
    assert typo["line_height"] == 24.0

    # Shadows
    assert len(tokens_data["shadows"]) == 1
    assert tokens_data["shadows"][0]["type"] == "DROP_SHADOW"
    assert tokens_data["shadows"][0]["offset_y"] == 2.0


def test_end_to_end_asset_export_persists_to_local_disk(tmp_path):
    client = FigmaClient(token="figd_mock_test")

    mock_api_resp = MagicMock()
    mock_api_resp.status_code = 200
    mock_api_resp.json.return_value = {
        "images": {"10:20": "https://figma-alpha.s3.amazonaws.com/test_render.png"}
    }

    binary_image = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...imagebytes"
    mock_download_resp = MagicMock()
    mock_download_resp.status_code = 200
    mock_download_resp.iter_content = MagicMock(return_value=[binary_image])

    out_dir = str(tmp_path / "exported_assets")

    with patch.object(client.session, "get", return_value=mock_api_resp):
        with patch("requests.get", return_value=mock_download_resp):
            export_result = client.export_node_image(
                file_key="file123",
                node_id="10:20",
                output_dir=out_dir,
                format="png",
            )

            assert export_result.node_id == "10:20"
            assert export_result.format == "png"
            assert export_result.file_size_bytes == len(binary_image)
            assert export_result.file_size_bytes > 0

            persisted_path = Path(export_result.local_path)
            assert persisted_path.exists()
            assert persisted_path.is_file()
            assert persisted_path.read_bytes() == binary_image


def test_mcp_rate_limit_resilience_integration():
    client = FigmaClient(token="figd_test", max_retries=2)

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "0.1"}

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"nodes": {"1:2": {"document": {"id": "1:2"}}}}

    with patch.object(client.session, "get", side_effect=[resp_429, resp_200]):
        with patch("time.sleep") as mock_sleep:
            res = client.get_file_nodes("testFileKey", ["1:2"])
            assert "nodes" in res
            assert "1:2" in res["nodes"]
            mock_sleep.assert_called_once_with(0.1)


def test_live_figma_token_connectivity():
    token = os.getenv("FIGMA_PERSONAL_ACCESS_TOKEN")
    if not token or not token.strip():
        pytest.skip("FIGMA_PERSONAL_ACCESS_TOKEN is not set; skipping live network check")

    client = FigmaClient(token=token.strip())
    try:
        user_info = client.get_me()
        assert "id" in user_info or "handle" in user_info or "email" in user_info
    except requests.RequestException as e:
        pytest.fail(f"Live Figma API request failed: {e}")
