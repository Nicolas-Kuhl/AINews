"""Playwright-based fetcher for JS-rendered web pages that block simple HTTP clients."""

from ainews.fetchers.html_scraper import discover_rss_link, scrape_html_page
from ainews.models import RawNewsItem


def fetch_web_feeds(
    feed_configs: list[dict], timeout: int = 15, max_items: int = 20
) -> list[RawNewsItem]:
    """Fetch multiple web-type feeds using a single headless browser instance."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [Web] playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    all_items: list[RawNewsItem] = []
    timeout_ms = timeout * 1000

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        page = context.new_page()

        for fc in feed_configs:
            name = fc["name"]
            url = fc["url"]
            print(f"  [Web] Fetching {name}...")

            try:
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)  # let JS render
                html = page.content()
            except Exception as e:
                print(f"  [Web] Error loading {name}: {e}")
                continue

            # Try RSS autodiscovery first
            rss_url = discover_rss_link(html, url)
            if rss_url and rss_url != url:
                try:
                    from ainews.fetchers.rss_fetcher import _parse_rss
                    page.goto(rss_url, timeout=timeout_ms, wait_until="domcontentloaded")
                    rss_html = page.content()
                    # Extract text content from the page for feedparser
                    items = _parse_rss(rss_html, name, max_items)
                    if items:
                        print(f"  [RSS]  {name} — {len(items)} items (autodiscovered via browser)")
                        all_items.extend(items)
                        continue
                except Exception:
                    pass

            # Scrape the rendered HTML
            items = scrape_html_page(html, url, name, max_items)
            if items:
                print(f"  [HTML] {name} — {len(items)} items (via browser)")
            else:
                print(f"  [Web] {name} — 0 items")
            all_items.extend(items)

        page.close()
        context.close()
        browser.close()

    return all_items
