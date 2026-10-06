"""Unit tests for FigmaClient and Figma models."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_agent.figma.client import FigmaAuthError, FigmaClient, TokenBucket
from harness_agent.figma.models import FigmaAssetExport, FigmaColor


def test_figma_color_hex_and_rgba_conversion():
    # Full opacity white
    white = FigmaColor(r=1.0, g=1.0, b=1.0, a=1.0)
    assert white.hex == "#FFFFFF"
    assert white.rgba_css == "rgba(255, 255, 255, 1.00)"

    # Full opacity black
    black = FigmaColor(r=0.0, g=0.0, b=0.0, a=1.0)
    assert black.hex == "#000000"
    assert black.rgba_css == "rgba(0, 0, 0, 1.00)"

    # Semi-transparent red
    red_trans = FigmaColor(r=1.0, g=0.0, b=0.0, a=0.5)
    assert red_trans.hex == "#FF000080"
    assert red_trans.rgba_css == "rgba(255, 0, 0, 0.50)"

    # Custom color rounding test
    custom = FigmaColor(r=0.1, g=0.5, b=0.9, a=0.8)
    # 0.1*255=25.5->26 (0x1A), 0.5*255=127.5->128 (0x80),
    # 0.9*255=229.5->230 (0xE6), 0.8*255=204 (0xCC)
    assert custom.hex == "#1A80E6CC"
    assert custom.rgba_css == "rgba(26, 128, 230, 0.80)"


def test_figma_client_init_token_from_env(monkeypatch):
    monkeypatch.delenv("FIGMA_PERSONAL_ACCESS_TOKEN", raising=False)
    with pytest.raises(FigmaAuthError, match="Figma token must not be empty"):
        FigmaClient()

    with pytest.raises(FigmaAuthError, match="Figma token must not be empty"):
        FigmaClient(token="   ")

    # Explicit token
    client = FigmaClient(token="figd_test123")
    assert client.token == "figd_test123"

    # From env var
    monkeypatch.setenv("FIGMA_PERSONAL_ACCESS_TOKEN", "figd_from_env")
    client_env = FigmaClient()
    assert client_env.token == "figd_from_env"


def test_figma_client_parse_url_formats():
    client = FigmaClient(token="figd_test")

    # File URL with hyphen node-id
    key, node = client.parse_figma_url(
        "https://www.figma.com/file/abc123XYZ/My-Design?node-id=10-25"
    )
    assert key == "abc123XYZ"
    assert node == "10:25"

    # Design URL with encoded node-id
    key, node = client.parse_figma_url(
        "https://www.figma.com/design/def456UVW/Project?node-id=1%3A2&t=xyz"
    )
    assert key == "def456UVW"
    assert node == "1:2"

    # URL without node-id
    key, node = client.parse_figma_url("https://figma.com/file/ghi789RST/Untitled")
    assert key == "ghi789RST"
    assert node is None

    # Invalid URL
    with pytest.raises(ValueError, match="Invalid Figma URL format"):
        client.parse_figma_url("https://other-site.com/file/12345")


def test_figma_client_get_me_mocked():
    client = FigmaClient(token="figd_test")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "123", "handle": "test_user", "email": "test@example.com"}

    with patch.object(client.session, "get", return_value=mock_resp) as mock_get:
        res = client.get_me()
        assert res["handle"] == "test_user"
        mock_get.assert_called_once_with("https://api.figma.com/v1/me", params=None, timeout=30.0)


def test_figma_client_get_nodes_mocked():
    client = FigmaClient(token="figd_test", cache_ttl_seconds=60)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"nodes": {"1:2": {"document": {"id": "1:2", "name": "Frame"}}}}

    with patch.object(client.session, "get", return_value=mock_resp) as mock_get:
        # First call fetches from API
        res1 = client.get_file_nodes("file123", ["1:2"])
        assert "1:2" in res1["nodes"]
        assert mock_get.call_count == 1

        # Second call within TTL hits cache
        res2 = client.get_file_nodes("file123", ["1:2"])
        assert "1:2" in res2["nodes"]
        assert mock_get.call_count == 1  # No additional network request


def test_figma_client_export_node_image_downloads_binary(tmp_path):
    client = FigmaClient(token="figd_test")

    mock_api_resp = MagicMock()
    mock_api_resp.status_code = 200
    mock_api_resp.json.return_value = {
        "images": {"1:2": "https://figma-alpha.s3.amazonaws.com/temp_image.png"}
    }

    mock_img_resp = MagicMock()
    mock_img_resp.status_code = 200
    binary_content = b"\x89PNG\r\n\x1a\nfake_png_data"
    mock_img_resp.iter_content = MagicMock(return_value=[binary_content])

    out_dir = str(tmp_path / "images")

    with patch.object(client.session, "get", return_value=mock_api_resp):
        with patch("requests.get", return_value=mock_img_resp):
            export = client.export_node_image("file123", "1:2", output_dir=out_dir)

            assert isinstance(export, FigmaAssetExport)
            assert export.node_id == "1:2"
            assert export.format == "png"
            assert export.file_size_bytes == len(binary_content)
            saved_file = Path(export.local_path)
            assert saved_file.exists()
            assert saved_file.read_bytes() == binary_content


def test_figma_client_rate_limiter_pacing():
    bucket = TokenBucket(rate_per_minute=120)  # 2 tokens per sec
    bucket.tokens = 1.0

    bucket.acquire()  # takes 1 token immediately
    assert bucket.tokens < 1.0

    # Acquire again, should sleep for ~0.5s
    with patch("time.sleep") as mock_sleep:
        bucket.acquire()
        mock_sleep.assert_called_once()


def test_figma_client_http_429_retry_after_backoff():
    client = FigmaClient(token="figd_test", max_retries=2)

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "1.5"}

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"success": True}

    with patch.object(client.session, "get", side_effect=[resp_429, resp_200]):
        with patch("time.sleep") as mock_sleep:
            res = client.get_me()
            assert res == {"success": True}
            mock_sleep.assert_called_once_with(1.5)
