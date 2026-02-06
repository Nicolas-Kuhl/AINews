from datetime import datetime

from dateutil import parser as dateparser
from ddgs import DDGS

from ainews.models import RawNewsItem


def search_news(query: str, max_results: int = 5) -> list[RawNewsItem]:
    """Search DuckDuckGo news for a query and return RawNewsItems."""
    items = []
    try:
        with DDGS() as ddgs:
            results = ddgs.news(query, max_results=max_results)
    except Exception as e:
        print(f"  [Search] Error searching '{query}': {e}")
        return []

    for r in results:
        title = r.get("title", "").strip()
        url = r.get("url", "").strip()
        if not title or not url:
            continue

        published = None
        date_str = r.get("date")
        if date_str:
            try:
                published = dateparser.parse(date_str)
            except (ValueError, OverflowError):
                pass

        source = r.get("source", "Web Search")
        body = r.get("body", "")
        if body:
            body = body[:500]

        items.append(
            RawNewsItem(
                title=title,
                url=url,
                source=source,
                published=published,
                description=body,
                fetched_via="web_search",
            )
        )

    return items


def search_all_queries(queries: list[str], max_results: int = 5) -> list[RawNewsItem]:
    """Run all configured search queries and return combined results."""
    all_items = []
    for query in queries:
        print(f"  [Search] Searching '{query}'...")
        items = search_news(query, max_results=max_results)
        print(f"  [Search]   Got {len(items)} items")
        all_items.extend(items)
    return all_items
