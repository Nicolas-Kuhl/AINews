"""Smart feed fetcher — routes feeds by type: rss, web, or auto-detect."""

import re
from datetime import datetime
from time import mktime
from typing import Optional

import feedparser
import httpx
from dateutil import parser as dateparser

from ainews.fetchers.html_scraper import discover_rss_link, scrape_html_page
from ainews.models import RawNewsItem

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_all_feeds(feeds: list[dict], timeout: int = 15, max_items: int = 20) -> list[RawNewsItem]:
    """Fetch all configured feeds, routing by type (rss / web / auto)."""
    all_items: list[RawNewsItem] = []
    web_feeds: list[dict] = []

    for fc in feeds:
        if not fc.get("enabled", True):
            print(f"  [Skip] {fc['name']} (disabled)")
            continue

        feed_type = fc.get("type", "auto")

        if feed_type == "rss":
            print(f"  [Feed] Fetching {fc['name']}...")
            items = _fetch_rss_direct(fc, timeout, max_items)
            all_items.extend(items)

        elif feed_type == "web":
            web_feeds.append(fc)

        else:  # auto
            print(f"  [Feed] Fetching {fc['name']}...")
            items = _fetch_auto(fc, timeout, max_items)
            all_items.extend(items)

    # Process all web-type feeds together with a single browser instance
    if web_feeds:
        from ainews.fetchers.web_page_fetcher import fetch_web_feeds
        all_items.extend(fetch_web_feeds(web_feeds, timeout, max_items))

    return all_items


# ---------------------------------------------------------------------------
# type: rss — feedparser directly on the URL
# ---------------------------------------------------------------------------

def _fetch_rss_direct(feed_config: dict, timeout: int, max_items: int) -> list[RawNewsItem]:
    """Fetch a known RSS/Atom feed URL using feedparser."""
    name = feed_config["name"]
    url = feed_config["url"]
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": _HEADERS["User-Agent"]})
    except Exception as e:
        print(f"  [RSS]  Error fetching {name}: {e}")
        return []

    if feed.bozo and not feed.entries:
        print(f"  [RSS]  Failed to parse {name}: {feed.bozo_exception}")
        return []

    items = _entries_to_items(feed.entries, name, max_items)
    print(f"  [RSS]  {name} — {len(items)} items")
    return items


# ---------------------------------------------------------------------------
# type: auto — httpx fetch, then auto-detect RSS vs HTML
# ---------------------------------------------------------------------------

def _fetch_auto(feed_config: dict, timeout: int, max_items: int) -> list[RawNewsItem]:
    """Fetch URL with httpx, auto-detect RSS/Atom vs HTML, scrape accordingly."""
    name = feed_config["name"]
    url = feed_config["url"]

    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True, headers=_HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [Feed] Error fetching {name}: {e}")
        return []

    body = resp.text
    ct = resp.headers.get("content-type", "")

    # If content looks like a feed, parse as RSS/Atom
    if _is_feed_content_type(ct) or _looks_like_feed_xml(body):
        items = _parse_rss(body, name, max_items)
        if items:
            print(f"  [RSS]  {name} — {len(items)} items")
            return items

    # HTML — try RSS autodiscovery
    rss_url = discover_rss_link(body, url)
    if rss_url and rss_url != url:
        try:
            rss_resp = httpx.get(rss_url, timeout=timeout, follow_redirects=True, headers=_HEADERS)
            rss_resp.raise_for_status()
            items = _parse_rss(rss_resp.text, name, max_items)
            if items:
                print(f"  [RSS]  {name} — {len(items)} items (autodiscovered)")
                return items
        except Exception:
            pass

    # Scrape the HTML page as fallback
    items = scrape_html_page(body, url, name, max_items)
    if items:
        print(f"  [HTML] {name} — {len(items)} items")
    else:
        print(f"  [Feed] {name} — 0 items")
    return items


# ---------------------------------------------------------------------------
# RSS/Atom parsing helpers
# ---------------------------------------------------------------------------

def _parse_rss(text: str, source_name: str, max_items: int) -> list[RawNewsItem]:
    """Parse RSS/Atom feed from raw text."""
    feed = feedparser.parse(text)
    if feed.bozo and not feed.entries:
        return []
    return _entries_to_items(feed.entries, source_name, max_items)


def _entries_to_items(entries, source_name: str, max_items: int) -> list[RawNewsItem]:
    """Convert feedparser entries to RawNewsItems."""
    items = []
    for entry in entries[:max_items]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        published = _parse_date(entry)
        description = entry.get("summary", "") or entry.get("description", "")
        if description:
            description = re.sub(r"<[^>]+>", "", description).strip()
            description = description[:500]

        items.append(RawNewsItem(
            title=title, url=link, source=source_name,
            published=published, description=description, fetched_via="rss",
        ))
    return items


def _parse_date(entry) -> Optional[datetime]:
    """Try to parse a date from a feed entry."""
    for field in ("published", "updated", "created"):
        raw = entry.get(f"{field}_parsed") or entry.get(field)
        if raw is None:
            continue
        if hasattr(raw, "tm_year"):
            try:
                return datetime.fromtimestamp(mktime(raw))
            except (OverflowError, ValueError, OSError):
                continue
        if isinstance(raw, str):
            try:
                return dateparser.parse(raw)
            except (ValueError, OverflowError):
                continue
    return None


# ---------------------------------------------------------------------------
# Content-type detection helpers
# ---------------------------------------------------------------------------

_FEED_CONTENT_TYPES = frozenset({
    "application/rss+xml", "application/atom+xml",
    "application/xml", "text/xml",
})


def _is_feed_content_type(ct: str) -> bool:
    ct_lower = ct.lower().split(";")[0].strip()
    return ct_lower in _FEED_CONTENT_TYPES


def _looks_like_feed_xml(body: str) -> bool:
    head = body[:2000].lstrip()
    if head.startswith("<rss") or head.startswith("<feed"):
        return True
    if "<?xml" in head and ("<channel>" in head or "<entry>" in head):
        return True
    return False
