from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from thefuzz import fuzz

from ainews.models import RawNewsItem


def normalize_url(url: str) -> str:
    """Normalize a URL for comparison: lowercase host, strip tracking params, trailing slashes."""
    try:
        parsed = urlparse(url.strip())
        # Lowercase scheme and host
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        # Remove www. prefix
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Strip common tracking parameters
        tracking_params = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "ref", "source"}
        params = parse_qs(parsed.query)
        filtered = {k: v for k, v in params.items() if k.lower() not in tracking_params}
        query = urlencode(filtered, doseq=True) if filtered else ""
        # Strip trailing slash from path
        path = parsed.path.rstrip("/")
        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return url.strip().lower()


def deduplicate(items: list[RawNewsItem], threshold: int = 80) -> list[RawNewsItem]:
    """Remove duplicates by URL normalization and fuzzy title matching."""
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    unique: list[RawNewsItem] = []

    for item in items:
        norm_url = normalize_url(item.url)

        # Exact URL match
        if norm_url in seen_urls:
            continue

        # Fuzzy title match against all kept titles
        title_lower = item.title.lower().strip()
        is_dup = False
        for kept_title in seen_titles:
            if fuzz.ratio(title_lower, kept_title) >= threshold:
                is_dup = True
                break

        if is_dup:
            continue

        seen_urls.add(norm_url)
        seen_titles.append(title_lower)
        unique.append(item)

    return unique
