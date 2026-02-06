"""Group similar news items by fuzzy title matching."""

import re
from urllib.parse import urlparse

from thefuzz import fuzz

from ainews.storage.database import Database

VENDOR_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "deepmind.com",
    "blogs.microsoft.com", "ai.meta.com", "about.fb.com",
    "stability.ai", "mistral.ai", "x.ai", "huggingface.co",
    "blog.google", "nvidia.com",
}

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "its", "it", "this", "that", "how", "what", "new", "into", "as", "has",
    "more", "can", "about", "will", "may", "up", "out", "just", "than",
    "introducing", "says", "could", "over", "why", "after",
}


def _significant_words(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", title.lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def _is_vendor_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        return any(host == d or host.endswith("." + d) for d in VENDOR_DOMAINS)
    except Exception:
        return False


def run_grouper(db: Database, threshold: int = 60) -> int:
    """Assign group_id to all items in the database. Returns number of groups created."""
    items = db.get_all_items_minimal()
    if not items:
        return 0

    # Clear existing groups and rebuild
    db.clear_all_groups()

    # Build groups: list of list of item dicts
    groups: list[list[dict]] = []

    for item in items:
        title_lower = item["title"].lower().strip()
        item_words = _significant_words(title_lower)
        matched_group = None

        for group in groups:
            # Only match against the first item (primary) to avoid chain-matching
            primary_title = group[0]["title"].lower().strip()
            shared = item_words & _significant_words(primary_title)
            if len(shared) >= 2 and fuzz.token_sort_ratio(title_lower, primary_title) >= threshold:
                matched_group = group
                break

        if matched_group:
            # Decide if new item should become primary (index 0)
            new_is_vendor = _is_vendor_url(item["url"])
            cur_is_vendor = _is_vendor_url(matched_group[0]["url"])
            if new_is_vendor and not cur_is_vendor:
                matched_group.insert(0, item)
            else:
                matched_group.append(item)
        else:
            groups.append([item])

    # Assign group_ids only for multi-item groups
    group_count = 0
    next_group_id = 1

    # Find current max group_id to avoid collisions
    for group in groups:
        if len(group) < 2:
            continue
        for member in group:
            db.set_group(member["id"], next_group_id)
        next_group_id += 1
        group_count += 1

    db.commit()
    return group_count
