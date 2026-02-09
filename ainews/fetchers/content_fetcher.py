"""Fetch full article content for news items using trafilatura."""

from __future__ import annotations

import asyncio
import logging

import httpx
import trafilatura

from ainews.models import RawNewsItem

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def _fetch_one(
    client: httpx.AsyncClient,
    item: RawNewsItem,
    max_length: int,
    semaphore: asyncio.Semaphore,
) -> None:
    """Fetch and extract content for a single item. Modifies item in-place."""
    async with semaphore:
        try:
            resp = await client.get(item.url, follow_redirects=True, headers=_HEADERS)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            logger.debug(f"  [Content] Failed to fetch {item.url}: {e}")
            return

        try:
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
        except Exception as e:
            logger.debug(f"  [Content] Failed to extract {item.url}: {e}")
            return

        if text:
            item.content = text[:max_length]


async def _fetch_all(
    items: list[RawNewsItem],
    max_length: int,
    max_concurrent: int,
    timeout: int,
) -> None:
    """Fetch content for all items concurrently."""
    semaphore = asyncio.Semaphore(max_concurrent)
    async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
        tasks = [_fetch_one(client, item, max_length, semaphore) for item in items]
        await asyncio.gather(*tasks)


def fetch_content_for_items(
    items: list[RawNewsItem],
    max_content_length: int = 10000,
    max_concurrent: int = 10,
    timeout: int = 15,
) -> int:
    """Fetch full article content for a list of RawNewsItems.

    Modifies items in-place, setting item.content for each successfully
    fetched article.

    Returns:
        Number of items that got content successfully.
    """
    if not items:
        return 0

    asyncio.run(_fetch_all(items, max_content_length, max_concurrent, timeout))

    return sum(1 for item in items if item.content)
