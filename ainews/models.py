from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class RawNewsItem:
    """A news item as fetched from a source, before processing."""
    title: str
    url: str
    source: str
    published: Optional[datetime] = None
    description: Optional[str] = None
    content: Optional[str] = None  # full article text
    fetched_via: str = ""  # "rss", "web_search", or "html_scrape"


@dataclass
class ProcessedNewsItem:
    """A news item after Claude API summarization and scoring."""
    title: str
    url: str
    source: str
    published: Optional[datetime] = None
    summary: str = ""
    content: Optional[str] = None  # full article text
    score: int = 0
    score_reasoning: str = ""
    learning_objectives: str = ""
    category: str = "Industry"
    fetched_via: str = ""
    processed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: Optional[int] = None
    acknowledged: bool = False
    group_id: Optional[int] = None
    lo_generated_with_opus: bool = False
