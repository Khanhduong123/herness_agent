"""Data models for web crawling and search."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from harness_agent.security import wrap_untrusted_content


class WebResult(BaseModel):
    """Result of a crawled or fetched web page."""

    url: str
    title: str = ""
    content: str = ""
    raw_html: Optional[str] = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)
    media: List[Dict[str, Any]] = Field(default_factory=list)
    links: List[Dict[str, Any]] = Field(default_factory=list)
    wrapped_content: str = ""

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if not self.wrapped_content and self.content:
            self.wrapped_content = wrap_untrusted_content(
                self.content, source_type="web", source_id=self.url
            )


class WebSearchResult(BaseModel):
    """Organic web search result item."""

    title: str
    url: str
    snippet: str = ""
    provider: str = "duckduckgo"
    rank: int = 1
