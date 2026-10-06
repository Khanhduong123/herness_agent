"""Figma API client implementation."""

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


class FigmaAuthError(ValueError):
    """Raised when Figma authentication credentials are missing or invalid."""

    pass


class FigmaAPIError(Exception):
    """Raised when Figma API returns an unexpected error."""

    pass


class TokenBucket:
    """Token Bucket rate limiter for managing request rate per minute."""

    def __init__(self, rate_per_minute: int) -> None:
        self.capacity = float(rate_per_minute)
        self.tokens = float(rate_per_minute)
        self.fill_rate = float(rate_per_minute) / 60.0  # tokens per second
        self.last_update = time.monotonic()

    def acquire(self) -> None:
        """Acquire a token, sleeping if necessary until one becomes available."""
        while True:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return

            needed = 1.0 - self.tokens
            sleep_time = needed / self.fill_rate if self.fill_rate > 0 else 1.0
            time.sleep(sleep_time)
            # Advance last_update by sleep_time so that even if time.monotonic
            # is not advancing (e.g. mocked sleep), tokens reflect the elapsed wait.
            self.last_update -= sleep_time


class FigmaClient:
    """Client for interacting with the Figma REST API."""

    BASE_URL = "https://api.figma.com/v1"

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        rate_limit_per_minute: int = 15,
        cache_ttl_seconds: int = 300,
    ) -> None:
        resolved_token = token or os.getenv("FIGMA_PERSONAL_ACCESS_TOKEN")
        if not resolved_token or not resolved_token.strip():
            raise FigmaAuthError(
                "Figma token must not be empty. Set FIGMA_PERSONAL_ACCESS_TOKEN in .env"
            )

        self.token = resolved_token.strip()
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limiter = TokenBucket(rate_limit_per_minute)
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Figma-Token": self.token,
                "Accept": "application/json",
            }
        )

    def _get_cache(self, key: str) -> Optional[Any]:
        if key in self._cache:
            timestamp, data = self._cache[key]
            if time.time() - timestamp < self.cache_ttl_seconds:
                return data
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any) -> None:
        self._cache[key] = (time.time(), data)

    def parse_figma_url(self, url: str) -> Tuple[str, Optional[str]]:
        """Parses a Figma URL to extract (file_key, node_id).

        Supports formats:
        - https://www.figma.com/file/<key>/<name>?node-id=<id>
        - https://www.figma.com/design/<key>/<name>?node-id=<id>
        - https://figma.com/file/<key>/...
        - Node id might be encoded like '1-2' or '1%3A2' or '1:2'
        """
        match = re.search(r"figma\.com/(?:file|design)/([a-zA-Z0-9_-]+)", url)
        if not match:
            raise ValueError(f"Invalid Figma URL format: {url}")

        file_key = match.group(1)
        node_match = re.search(r"node-id=([^&]+)", url)
        node_id = None
        if node_match:
            node_id = node_match.group(1).replace("%3A", ":").replace("-", ":")

        return file_key, node_id

    def _request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Performs a GET request with rate limiting and exponential backoff on 429."""
        url = (
            f"{self.BASE_URL}{endpoint}"
            if endpoint.startswith("/")
            else f"{self.BASE_URL}/{endpoint}"
        )
        retries = 0

        while True:
            self.rate_limiter.acquire()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code == 429:
                    retries += 1
                    if retries > self.max_retries:
                        response.raise_for_status()

                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            sleep_duration = float(retry_after)
                        except ValueError:
                            sleep_duration = 2.0**retries
                    else:
                        sleep_duration = 2.0**retries

                    time.sleep(sleep_duration)
                    continue

                response.raise_for_status()
                return response.json()
            except requests.HTTPError as e:
                if response.status_code == 429 and retries <= self.max_retries:
                    continue
                raise FigmaAPIError(f"HTTP request failed: {e}") from e
            except requests.RequestException as e:
                raise FigmaAPIError(f"Network error communicating with Figma: {e}") from e

    def get_me(self) -> Dict[str, Any]:
        """Fetches current user profile from Figma API."""
        return self._request("/me")

    def get_file(self, file_key: str, depth: Optional[int] = 2) -> Dict[str, Any]:
        """Fetches file document tree with caching."""
        cache_key = f"file:{file_key}:depth:{depth}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        params = {}
        if depth is not None:
            params["depth"] = depth

        data = self._request(f"/files/{file_key}", params=params)
        self._set_cache(cache_key, data)
        return data

    def get_file_nodes(self, file_key: str, node_ids: List[str]) -> Dict[str, Any]:
        """Fetches specific nodes from a Figma file with caching."""
        sorted_ids = sorted(node_ids)
        cache_key = f"nodes:{file_key}:{','.join(sorted_ids)}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        params = {"ids": ",".join(node_ids)}
        data = self._request(f"/files/{file_key}/nodes", params=params)
        self._set_cache(cache_key, data)
        return data

    def export_node_image(
        self,
        file_key: str,
        node_id: str,
        output_dir: str = "assets/images",
        format: str = "png",
        scale: float = 2.0,
    ) -> Any:
        """Fetches S3 temporary image URL from /v1/images, downloads the binary payload,
        persists to disk, and returns FigmaAssetExport with local relative path."""
        from harness_agent.figma.models import FigmaAssetExport

        params = {
            "ids": node_id,
            "format": format,
            "scale": scale,
        }
        res = self._request(f"/images/{file_key}", params=params)
        images = res.get("images", {})
        image_url = images.get(node_id)
        if not image_url:
            raise FigmaAPIError(f"No image URL returned for node {node_id}")

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        clean_node_id = node_id.replace(":", "_").replace("-", "_")
        filename = f"{clean_node_id}.{format}"
        target_file = out_path / filename

        # Download image binary with cleanup on error
        try:
            img_res = requests.get(image_url, timeout=self.timeout, stream=True)
            img_res.raise_for_status()

            with open(target_file, "wb") as f:
                for chunk in img_res.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            file_size = target_file.stat().st_size
            return FigmaAssetExport(
                node_id=node_id,
                local_path=str(target_file).replace("\\", "/"),
                format=format,
                file_size_bytes=file_size,
            )
        except Exception as e:
            if target_file.exists():
                try:
                    target_file.unlink()
                except OSError:
                    pass
            raise FigmaAPIError(f"Failed to download image for node {node_id}: {e}") from e
