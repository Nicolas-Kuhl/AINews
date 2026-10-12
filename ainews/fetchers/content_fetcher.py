"""Fetch full article content for news items using trafilatura."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
import trafilatura

from ainews.models import RawNewsItem
from ainews.net_safety import is_public_url

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# Article pages rarely exceed a few hundred KB; stop reading beyond this so a
# huge or endless response can't exhaust memory.
MAX_BODY_BYTES = 2_000_000
_HTML_TYPES = ("text/html", "application/xhtml+xml")


class UnsafeURLError(httpx.RequestError):
    """Refused to fetch a URL that resolves to a non-public address."""


async def _guard_request(request: httpx.Request) -> None:
    # Runs for every hop, so a public URL can't redirect into the VPC or
    # the instance-metadata endpoint. (URLs come from feeds and from links
    # Claude extracted out of inbound email.)
    if not await asyncio.to_thread(is_public_url, str(request.url)):
        raise UnsafeURLError(f"refusing non-public URL {request.url}", request=request)


def _make_client(timeout: int, transport: Optional[httpx.AsyncBaseTransport] = None):
    return httpx.AsyncClient(
        timeout=timeout,
        transport=transport,
        follow_redirects=True,
        max_redirects=5,
        event_hooks={"request": [_guard_request]},
    )


async def _read_capped(resp: httpx.Response, cap: int) -> bytes:
    chunks, total = [], 0
    async for chunk in resp.aiter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= cap:
            break
    return b"".join(chunks)[:cap]


async def _fetch_one(
    client: httpx.AsyncClient,
    item: RawNewsItem,
    max_length: int,
    semaphore: asyncio.Semaphore,
) -> None:
    """Fetch and extract content for a single item. Modifies item in-place."""
    async with semaphore:
        try:
            async with client.stream("GET", item.url, headers=_HEADERS) as resp:
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and ctype not in _HTML_TYPES:
                    logger.debug(f"  [Content] Skipping {ctype} at {item.url}")
                    return
                body = await _read_capped(resp, MAX_BODY_BYTES)
                html = body.decode(resp.charset_encoding or "utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"  [Content] Failed to fetch {item.url}: {e}")
            return

        try:
            text = await asyncio.to_thread(
                trafilatura.extract,
                html,
                include_comments=False,
                include_tables=False,
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
    async with _make_client(timeout) as client:
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
