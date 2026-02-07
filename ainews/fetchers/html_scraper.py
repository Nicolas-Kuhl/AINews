"""HTML scraper fallback for pages that aren't RSS/Atom feeds."""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

from dateutil import parser as dateparser
from lxml import html as lxml_html

from ainews.models import RawNewsItem


def discover_rss_link(html_text: str, base_url: str) -> Optional[str]:
    """Look for RSS/Atom autodiscovery <link> in HTML <head>."""
    try:
        doc = lxml_html.fromstring(html_text)
    except Exception:
        return None

    for link in doc.cssselect('link[rel="alternate"]'):
        link_type = (link.get("type") or "").lower()
        if link_type in ("application/rss+xml", "application/atom+xml"):
            href = link.get("href", "").strip()
            if href:
                return urljoin(base_url, href)
    return None


def scrape_html_page(
    html_text: str, base_url: str, source_name: str, max_items: int = 20
) -> list[RawNewsItem]:
    """Extract news items from an HTML page using a cascade of heuristics."""
    try:
        doc = lxml_html.fromstring(html_text)
        doc.make_links_absolute(base_url)
    except Exception:
        return []

    # Try heuristics in order; use first that yields results
    for strategy in (_try_articles, _try_heading_links, _try_list_cards, _try_generic_links):
        items = strategy(doc, base_url, source_name)
        if items:
            items = _deduplicate_items(items)
            return items[:max_items]

    return []


# ---------------------------------------------------------------------------
# Heuristic strategies
# ---------------------------------------------------------------------------

def _try_articles(doc, base_url: str, source_name: str) -> list[RawNewsItem]:
    """Strategy 1: <article> elements with a title link inside."""
    items = []
    for article in doc.cssselect("article"):
        link_el = None
        for sel in ("h1 a", "h2 a", "h3 a", "h4 a", "a[href]"):
            found = article.cssselect(sel)
            if found:
                link_el = found[0]
                break
        if link_el is None:
            continue
        href = link_el.get("href", "").strip()
        title = (link_el.text_content() or "").strip()
        if not href or not title or not _is_article_url(href, base_url):
            continue
        items.append(RawNewsItem(
            title=title, url=href, source=source_name,
            published=_extract_date_near(article),
            description=_extract_description(article, title),
            fetched_via="html_scrape",
        ))
    return items


def _try_heading_links(doc, base_url: str, source_name: str) -> list[RawNewsItem]:
    """Strategy 2: headings with links — handles both h2>a and a>h2 patterns."""
    items = []
    seen_urls: set[str] = set()

    # Pattern A: heading contains a link (h2 a[href]) — traditional blogs
    # Pattern B: link contains a heading (a[href] h2) — modern card layouts
    selectors = [
        # (css_selector, is_reverse)
        ("h1 a[href]", False), ("h2 a[href]", False), ("h3 a[href]", False), ("h4 a[href]", False),
        ("a[href] h1", True), ("a[href] h2", True), ("a[href] h3", True), ("a[href] h4", True),
    ]
    for sel, reverse in selectors:
        for el in doc.cssselect(sel):
            if reverse:
                # el is the heading; walk up to find the <a> ancestor
                heading = el
                a = heading.getparent()
                while a is not None and a.tag != "a":
                    a = a.getparent()
                if a is None:
                    continue
                title = (heading.text_content() or "").strip()
                href = a.get("href", "").strip()
                context = a.getparent()
            else:
                # el is the <a> inside a heading
                a = el
                title = (a.text_content() or "").strip()
                href = a.get("href", "").strip()
                context = a.getparent()
                if context is not None:
                    context = context.getparent()

            if not href or not title or not _is_article_url(href, base_url):
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            items.append(RawNewsItem(
                title=title, url=href, source=source_name,
                published=_extract_date_near(context) if context is not None else None,
                description=_extract_description(context, title) if context is not None else None,
                fetched_via="html_scrape",
            ))
    return items


def _try_list_cards(doc, base_url: str, source_name: str) -> list[RawNewsItem]:
    """Strategy 3: list/card patterns — need ≥3 matching siblings."""
    selectors = (
        "li", ".post", ".card",
        "[class*='entry']", "[class*='release']", "[class*='changelog']",
        "[class*='item']", "[class*='article']",
    )
    for sel in selectors:
        elements = doc.cssselect(sel)
        if len(elements) < 3:
            continue
        items = []
        for el in elements:
            links = el.cssselect("a[href]")
            if not links:
                continue
            # Pick the link with the longest text as the title link
            best = max(links, key=lambda a: len((a.text_content() or "").strip()))
            href = best.get("href", "").strip()
            title = (best.text_content() or "").strip()
            if not href or not title or len(title) < 5 or not _is_article_url(href, base_url):
                continue
            items.append(RawNewsItem(
                title=title, url=href, source=source_name,
                published=_extract_date_near(el),
                description=_extract_description(el, title),
                fetched_via="html_scrape",
            ))
        if len(items) >= 3:
            return items
    return []


def _try_generic_links(doc, base_url: str, source_name: str) -> list[RawNewsItem]:
    """Strategy 4: score all <a> tags and take the best ones."""
    scored: list[tuple[float, str, str, lxml_html.HtmlElement]] = []

    for a in doc.cssselect("a[href]"):
        href = a.get("href", "").strip()
        title = (a.text_content() or "").strip()
        if not href or not title or len(title) < 10 or not _is_article_url(href, base_url):
            continue

        score = 0.0
        # Longer link text is better (likely a headline)
        score += min(len(title), 120) / 20.0
        # Deeper paths are more likely to be articles
        path = urlparse(href).path.rstrip("/")
        depth = path.count("/")
        score += min(depth, 5) * 0.5
        # Slug-like paths (words separated by hyphens)
        if re.search(r"/[\w]+-[\w]+-", path):
            score += 2.0
        # Date patterns in URL
        if re.search(r"/\d{4}/\d{2}", path):
            score += 2.0
        # Penalise very short or generic titles
        if len(title) < 20:
            score -= 1.0

        scored.append((score, href, title, a))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    items = []
    seen_urls: set[str] = set()
    for score_val, href, title, a in scored:
        if href in seen_urls:
            continue
        seen_urls.add(href)
        parent = a.getparent()
        items.append(RawNewsItem(
            title=title, url=href, source=source_name,
            published=_extract_date_near(parent) if parent is not None else None,
            description=_extract_description(parent, title) if parent is not None else None,
            fetched_via="html_scrape",
        ))
        if len(items) >= 30:
            break
    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NAV_PATTERNS = re.compile(
    r"/(tag|tags|category|categories|author|authors|search|login|signin|signup|"
    r"register|account|contact|about|privacy|terms|faq|help|#|javascript:)",
    re.IGNORECASE,
)


def _is_article_url(url: str, base_url: str) -> bool:
    """Reject navigation / utility links; require same domain, deeper than base."""
    try:
        parsed = urlparse(url)
        base_parsed = urlparse(base_url)
    except Exception:
        return False

    # Must be http(s)
    if parsed.scheme not in ("http", "https"):
        return False
    # Same domain
    if parsed.netloc and base_parsed.netloc and parsed.netloc != base_parsed.netloc:
        return False
    # Reject nav patterns
    if _NAV_PATTERNS.search(parsed.path + ("?" + parsed.query if parsed.query else "")):
        return False
    # Must have a path deeper than just /
    if parsed.path.strip("/") == "":
        return False

    return True


def _extract_date_near(element) -> Optional[datetime]:
    """Try to find a date near the given element."""
    if element is None:
        return None
    # <time datetime="">
    for time_el in element.cssselect("time[datetime]"):
        raw = time_el.get("datetime", "").strip()
        if raw:
            try:
                return dateparser.parse(raw)
            except (ValueError, OverflowError):
                pass
    # <time> text
    for time_el in element.cssselect("time"):
        raw = (time_el.text_content() or "").strip()
        if raw:
            try:
                return dateparser.parse(raw)
            except (ValueError, OverflowError):
                pass
    # Elements with date-like class
    for date_el in element.cssselect("[class*='date']"):
        raw = (date_el.text_content() or "").strip()
        if raw and len(raw) < 80:
            try:
                return dateparser.parse(raw)
            except (ValueError, OverflowError):
                pass
    return None


def _extract_description(element, title: str) -> Optional[str]:
    """First <p> that isn't the title text, max 500 chars."""
    if element is None:
        return None
    for p in element.cssselect("p"):
        text = (p.text_content() or "").strip()
        if text and text != title and len(text) > 20:
            return text[:500]
    return None


def _deduplicate_items(items: list[RawNewsItem]) -> list[RawNewsItem]:
    """Remove duplicate items by URL."""
    seen: set[str] = set()
    result = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            result.append(item)
    return result
