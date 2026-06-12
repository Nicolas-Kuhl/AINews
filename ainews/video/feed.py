"""Episode RSS feed — publishes rendered videos as a subscribable video podcast.

Builds an RSS 2.0 feed with ``<enclosure>`` entries (plus the iTunes
namespace tags podcast apps expect) from the rendered MP4s in
``data/videos/`` and their matching episode scripts in
``data/video_scripts/``. The feed is written next to the videos so nginx
serves everything from one location:

    https://<host>/videos/feed.xml   ← subscribe to this
    https://<host>/videos/<date>.mp4

An episode appears in the feed only when both its MP4 and its script JSON
exist; the script supplies the title and show-notes description.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ainews.eyrean.com/videos"
DEFAULT_SITE_URL = "https://ainews.eyrean.com"
DEFAULT_ARTWORK_URL = "https://ainews.eyrean.com/videos/cover.jpg"
DEFAULT_OWNER_EMAIL = "nicolas.kuhl.au@gmail.com"
# Apple category taxonomy — see podcastsconnect.apple.com categories list
DEFAULT_CATEGORIES = [("Technology", None), ("News", "Tech News")]
DEFAULT_DESCRIPTION = (
    "A five-minute daily rundown of the AI news that actually matters — "
    "model releases, industry moves, research, and the occasional broccoli "
    "farmer automating his harvest. Written, voiced, and produced "
    "automatically every day. Slightly irreverent, always sourced."
)

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.mp4$")


def _episode_description(script: dict) -> str:
    """Show notes: the cold open plus a headline list with sources."""
    lines = [script.get("cold_open", "").strip(), ""]
    for i, seg in enumerate(script.get("segments", []), 1):
        lines.append(f"{i}. {seg.get('headline', '')} ({seg.get('source', '')})")
    return "\n".join(lines).strip()


def _duration_seconds(script: dict) -> Optional[int]:
    secs = script.get("meta", {}).get("estimated_runtime_seconds")
    return int(secs) if secs else None


def collect_episodes(videos_dir: Path, scripts_dir: Path) -> "list[dict]":
    """Pair MP4s with their scripts, newest first. Unmatched MP4s are skipped."""
    episodes = []
    for mp4 in sorted(videos_dir.glob("*.mp4"), reverse=True):
        m = _DATE_RE.match(mp4.name)
        if not m:
            continue  # preview frames, partial renders etc.
        date = m.group(1)
        script_path = scripts_dir / f"{date}.json"
        if not script_path.exists():
            logger.warning("Feed: %s has no matching script, skipping", mp4.name)
            continue
        with open(script_path, encoding="utf-8") as f:
            script = json.load(f)
        episodes.append({
            "date": date,
            "title": script.get("title", f"Episode {date}"),
            "description": _episode_description(script),
            "duration_seconds": _duration_seconds(script),
            "size_bytes": mp4.stat().st_size,
            "pub_dt": datetime.fromtimestamp(mp4.stat().st_mtime, tz=timezone.utc),
        })
    return episodes


def _categories_xml(categories: "list[tuple[str, Optional[str]]]") -> str:
    parts = []
    for top, sub in categories:
        if sub:
            parts.append(
                f'    <itunes:category text="{escape(top)}">\n'
                f'      <itunes:category text="{escape(sub)}"/>\n'
                f'    </itunes:category>'
            )
        else:
            parts.append(f'    <itunes:category text="{escape(top)}"/>')
    return "\n".join(parts)


def build_feed_xml(
    episodes: "list[dict]",
    *,
    base_url: str = DEFAULT_BASE_URL,
    site_url: str = DEFAULT_SITE_URL,
    show_name: str = "The Daily Prompt",
    tagline: str = "AI news. Daily. Slightly irreverent.",
    description: str = DEFAULT_DESCRIPTION,
    artwork_url: str = DEFAULT_ARTWORK_URL,
    owner_email: str = DEFAULT_OWNER_EMAIL,
    categories: "Optional[list[tuple[str, Optional[str]]]]" = None,
    max_items: int = 30,
) -> str:
    items = []
    for ep in episodes[:max_items]:
        video_url = f"{base_url}/{ep['date']}.mp4"
        duration = (
            f"\n      <itunes:duration>{ep['duration_seconds']}</itunes:duration>"
            if ep.get("duration_seconds") else ""
        )
        items.append(f"""    <item>
      <title>{escape(ep["title"])}</title>
      <description>{escape(ep["description"])}</description>
      <pubDate>{format_datetime(ep["pub_dt"])}</pubDate>
      <guid isPermaLink="false">ainews-episode-{ep["date"]}</guid>
      <link>{escape(video_url)}</link>
      <enclosure url="{escape(video_url)}" length="{ep["size_bytes"]}" type="video/mp4"/>{duration}
      <itunes:episodeType>full</itunes:episodeType>
    </item>""")

    now = format_datetime(datetime.now(timezone.utc))
    items_xml = "\n".join(items)
    cats_xml = _categories_xml(categories or DEFAULT_CATEGORIES)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(show_name)}</title>
    <link>{escape(site_url)}</link>
    <description>{escape(description)}</description>
    <itunes:summary>{escape(tagline)}</itunes:summary>
    <language>en-au</language>
    <lastBuildDate>{now}</lastBuildDate>
    <atom:link href="{escape(base_url)}/feed.xml" rel="self" type="application/rss+xml"/>
    <itunes:author>{escape(show_name)}</itunes:author>
    <itunes:owner>
      <itunes:name>{escape(show_name)}</itunes:name>
      <itunes:email>{escape(owner_email)}</itunes:email>
    </itunes:owner>
    <itunes:image href="{escape(artwork_url)}"/>
{cats_xml}
    <itunes:type>episodic</itunes:type>
    <itunes:explicit>false</itunes:explicit>
{items_xml}
  </channel>
</rss>
"""


def write_episode_feed(
    videos_dir: Path,
    scripts_dir: Path,
    *,
    base_url: str = DEFAULT_BASE_URL,
    site_url: str = DEFAULT_SITE_URL,
    show_name: str = "The Daily Prompt",
) -> "tuple[Path, int]":
    """Regenerate feed.xml in videos_dir. Returns (path, episode_count)."""
    episodes = collect_episodes(videos_dir, scripts_dir)
    xml = build_feed_xml(
        episodes, base_url=base_url, site_url=site_url, show_name=show_name,
    )
    feed_path = videos_dir / "feed.xml"
    feed_path.write_text(xml, encoding="utf-8")
    logger.info("Episode feed written: %s (%d episodes)", feed_path, len(episodes))
    return feed_path, len(episodes)
