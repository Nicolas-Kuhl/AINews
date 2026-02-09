from __future__ import annotations

import json
import logging
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import anthropic
from rapidfuzz import fuzz

from ainews.models import RawNewsItem

logger = logging.getLogger(__name__)


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


def deduplicate(
    items: list[RawNewsItem],
    threshold: int = 80,
    existing_titles: list[str] | None = None,
    existing_urls: set[str] | None = None,
    borderline_low: int = 50,
) -> tuple[list[RawNewsItem], list[tuple[str, str]]]:
    """Remove duplicates by URL normalization and fuzzy title matching.

    Args:
        items: New items to deduplicate.
        threshold: Fuzzy match threshold (0-100).
        existing_titles: Lowercased titles already in the database.
        existing_urls: Raw URLs already in the database (will be normalized).
        borderline_low: Lower bound for borderline matches sent to semantic dedup.

    Returns:
        (unique_items, borderline_pairs) — borderline_pairs are (new_title, existing_title)
        tuples with fuzzy scores between borderline_low and threshold.
    """
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    unique: list[RawNewsItem] = []
    borderline: list[tuple[str, str]] = []

    # Seed with existing DB data so new items are checked against history
    if existing_urls:
        seen_urls.update(normalize_url(u) for u in existing_urls)
    if existing_titles:
        seen_titles.extend(existing_titles)

    for item in items:
        norm_url = normalize_url(item.url)

        # Exact normalized URL match (batch + DB)
        if norm_url in seen_urls:
            continue

        # Fuzzy title match against kept titles + DB titles
        title_lower = item.title.lower().strip()
        is_dup = False
        best_borderline: tuple[str, str] | None = None
        best_borderline_score = 0
        for kept_title in seen_titles:
            score = fuzz.token_set_ratio(title_lower, kept_title)
            if score >= threshold:
                is_dup = True
                break
            if borderline_low <= score < threshold and score > best_borderline_score:
                best_borderline = (item.title, kept_title)
                best_borderline_score = score

        if is_dup:
            continue

        # Track the closest borderline match for semantic review
        if best_borderline:
            borderline.append(best_borderline)

        seen_urls.add(norm_url)
        seen_titles.append(title_lower)
        unique.append(item)

    return unique, borderline


def semantic_dedup(
    client: anthropic.Anthropic,
    model: str,
    borderline_pairs: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Use Claude to judge whether borderline title pairs are about the same story.

    Instead of removing duplicates, returns confirmed same-story pairs so they
    can be grouped together (showing all sources for a single story).

    Args:
        client: Anthropic API client.
        model: Model ID to use (e.g. claude-sonnet-4-5-20250929).
        borderline_pairs: (new_title, matched_existing_title) pairs to judge.

    Returns:
        List of (new_title, existing_title) pairs confirmed as same story.
    """
    if not borderline_pairs:
        return []

    # Build the prompt with all borderline pairs
    pairs_text = "\n".join(
        f'{i+1}. A: "{new}"\n   B: "{existing}"'
        for i, (new, existing) in enumerate(borderline_pairs)
    )

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""You are a news deduplication assistant. For each pair below, determine if headline A is about the same specific news story/event as headline B.

Answer ONLY with a JSON array of pair numbers that ARE about the same story. If none match, return an empty array [].

Be strict: two articles must be about the same specific event or announcement to count. Articles about the same general topic but different events are NOT the same story.

{pairs_text}

Return ONLY a JSON array, e.g. [1, 3] or []. No other text.""",
        }],
    )

    # Parse Claude's response
    response_text = response.content[0].text.strip()
    try:
        match_indices = json.loads(response_text)
    except json.JSONDecodeError:
        logger.warning(f"Semantic dedup: could not parse response: {response_text}")
        return []

    if not match_indices:
        return []

    # Return the confirmed same-story pairs
    confirmed: list[tuple[str, str]] = []
    for idx in match_indices:
        if 1 <= idx <= len(borderline_pairs):
            confirmed.append(borderline_pairs[idx - 1])

    if confirmed:
        logger.info(f"  Semantic dedup found {len(confirmed)} same-story pair{'s' if len(confirmed) != 1 else ''}")

    return confirmed
