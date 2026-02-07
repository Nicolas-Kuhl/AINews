"""RSS feed generator for high-priority AI news items."""

from datetime import datetime
from email.utils import formatdate
from typing import List
from xml.sax.saxutils import escape

from ainews.models import NewsItem


def generate_rss_feed(items: List[NewsItem], min_score: int = 8) -> str:
    """
    Generate an RSS 2.0 feed from news items.

    Args:
        items: List of NewsItem objects to include
        min_score: Minimum score threshold (default: 8)

    Returns:
        RSS feed as XML string
    """
    # Filter items by score
    filtered_items = [item for item in items if item.score >= min_score]

    # Sort by published date (newest first)
    filtered_items.sort(key=lambda x: x.published or datetime.min, reverse=True)

    # Limit to most recent 50 items
    filtered_items = filtered_items[:50]

    # Build RSS XML
    rss_parts = [
        '<?xml version="1.0" encoding="UTF-8" ?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        '<channel>',
        f'<title>AI News Aggregator - High Priority (Score {min_score}+)</title>',
        '<link>https://github.com/yourusername/ainews</link>',
        '<description>High-priority AI news items rated 8 or above</description>',
        '<language>en-us</language>',
        f'<lastBuildDate>{formatdate(datetime.now().timestamp())}</lastBuildDate>',
        '<atom:link href="https://yourdomain.com/rss/high-priority.xml" rel="self" type="application/rss+xml" />',
    ]

    # Add items
    for item in filtered_items:
        rss_parts.extend(_item_to_rss(item))

    rss_parts.extend([
        '</channel>',
        '</rss>'
    ])

    return '\n'.join(rss_parts)


def _item_to_rss(item: NewsItem) -> List[str]:
    """Convert a NewsItem to RSS item XML."""
    # Escape HTML content
    title = escape(item.title)
    source = escape(item.source)

    # Build description from summary and score reasoning
    description_parts = []
    if item.summary:
        description_parts.append(f"<p><strong>Summary:</strong> {escape(item.summary)}</p>")
    if item.score_reasoning:
        description_parts.append(f"<p><strong>Score Reasoning:</strong> {escape(item.score_reasoning)}</p>")
    description_parts.append(f"<p><strong>Score:</strong> {item.score}/10</p>")
    description_parts.append(f"<p><strong>Category:</strong> {escape(item.category)}</p>")

    description = ''.join(description_parts)

    # Format publication date
    pub_date = ""
    if item.published:
        pub_date = f"<pubDate>{formatdate(item.published.timestamp())}</pubDate>"

    # Build item XML
    return [
        '<item>',
        f'<title>[{item.score}] {title}</title>',
        f'<link>{escape(item.url)}</link>',
        f'<description><![CDATA[{description}]]></description>',
        f'<source>{source}</source>',
        f'<guid isPermaLink="false">ainews-{item.id}</guid>',
        pub_date,
        '</item>',
    ]


def save_rss_feed(db, output_path: str, min_score: int = 8):
    """
    Generate and save RSS feed to a file.

    Args:
        db: Database instance
        output_path: Path to save RSS XML file
        min_score: Minimum score threshold (default: 8)
    """
    # Query all unacknowledged items
    items = db.query_items(
        min_score=min_score,
        show_acknowledged=False,
        sort_by="published",
        sort_dir="DESC"
    )

    # Generate RSS XML
    rss_xml = generate_rss_feed(items, min_score=min_score)

    # Write to file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(rss_xml)

    return len([item for item in items if item.score >= min_score])
