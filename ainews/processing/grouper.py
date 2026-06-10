"""Group similar news items by fuzzy title matching."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

import anthropic
from rapidfuzz import fuzz

from ainews.storage.database import Database

logger = logging.getLogger(__name__)

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


def run_grouper(
    db: Database,
    threshold: int = 48,
    min_shared_words: int = 3,
) -> int:
    """Assign group_id to all items in the database. Returns number of groups created.

    A new item joins a group when there exists at least one member of that
    group with ≥ ``min_shared_words`` shared significant words AND a fuzzy
    title score ≥ ``threshold``. The new item joins the BEST-matching group
    (highest fuzzy score across any member) — this catches cross-publisher
    rewrites where the late entrant phrasing diverges from the original
    primary but still aligns with a more recent member.
    """
    items = db.get_all_items_minimal()
    if not items:
        return 0

    # Clear existing groups and rebuild
    db.clear_all_groups()

    # Cache significant-word sets so we don't recompute O(n) times per item
    item_word_cache: dict[int, set[str]] = {}

    def words_of(it: dict) -> set[str]:
        cached = item_word_cache.get(it["id"])
        if cached is None:
            cached = _significant_words(it["title"].lower().strip())
            item_word_cache[it["id"]] = cached
        return cached

    # Build groups: list of list of item dicts
    groups: list[list[dict]] = []

    for item in items:
        title_lower = item["title"].lower().strip()
        item_words = words_of(item)
        if len(item_words) < min_shared_words:
            # Title too short to match meaningfully — start its own group
            groups.append([item])
            continue

        best_group: list[dict] | None = None
        best_score = -1

        for group in groups:
            for member in group:
                shared = item_words & words_of(member)
                if len(shared) < min_shared_words:
                    continue
                score = fuzz.token_sort_ratio(
                    title_lower, member["title"].lower().strip()
                )
                if score >= threshold and score > best_score:
                    best_group = group
                    best_score = score
                    break  # this group already matches; check other groups

        if best_group is not None:
            # Decide if new item should become primary (index 0)
            new_is_vendor = _is_vendor_url(item["url"])
            cur_is_vendor = _is_vendor_url(best_group[0]["url"])
            if new_is_vendor and not cur_is_vendor:
                best_group.insert(0, item)
            else:
                best_group.append(item)
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


def deep_semantic_dedup(
    db: Database,
    client: anthropic.Anthropic,
    model: str,
    fuzzy_low: int = 30,
    fuzzy_high: int = 70,
    since_days: int | None = None,
    max_candidates: int = 400,
) -> int:
    """Scan unacknowledged DB items for semantic duplicates using Claude.

    Finds pairs of items with borderline fuzzy similarity (between fuzzy_low
    and fuzzy_high) that share at least one significant keyword, then asks
    Claude to confirm whether they're the same story in a single API call.
    Confirmed pairs are grouped together, with vendor-sourced items preferred
    as primary.

    Args:
        db: Database instance.
        client: Anthropic API client.
        model: Model ID for Claude.
        fuzzy_low: Minimum fuzzy score to consider a pair.
        fuzzy_high: Maximum fuzzy score (above this, run_grouper already catches them).
        since_days: When set, restrict to items published within the last N days
            (keeps the daily pipeline call cheap). ``None`` scans everything.
        max_candidates: Hard cap on the number of pairs sent to Claude in one
            call. Highest-fuzzy pairs are kept first.

    Returns:
        Number of new groupings created.
    """
    items = db.get_all_items_for_dedup(unacknowledged_only=True)
    if since_days is not None:
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        recent_ids = {
            r["id"]
            for r in db.conn.execute(
                "SELECT id FROM news_items WHERE published >= ?", (cutoff,)
            ).fetchall()
        }
        items = [it for it in items if it["id"] in recent_ids]
    if len(items) < 2:
        return 0

    # Build candidate pairs: share keywords + borderline fuzzy score
    candidates: list[tuple[dict, dict]] = []
    for i in range(len(items)):
        title_i = items[i]["title"].lower().strip()
        words_i = _significant_words(title_i)
        if not words_i:
            continue
        for j in range(i + 1, len(items)):
            title_j = items[j]["title"].lower().strip()
            words_j = _significant_words(title_j)
            # Must share at least one significant word
            if not words_i & words_j:
                continue
            score = fuzz.token_set_ratio(title_i, title_j)
            if fuzzy_low <= score <= fuzzy_high:
                candidates.append((items[i], items[j]))

    if not candidates:
        logger.info("  Deep semantic dedup: no borderline candidates found.")
        return 0

    # Cap candidates to keep the API call bounded; prefer pairs with the most
    # shared keywords (more likely to be true dupes) before falling back to
    # higher fuzzy scores.
    if len(candidates) > max_candidates:
        def _candidate_strength(pair: tuple[dict, dict]) -> tuple[int, int]:
            a, b = pair
            shared = _significant_words(a["title"].lower()) & _significant_words(b["title"].lower())
            ratio = fuzz.token_set_ratio(a["title"].lower(), b["title"].lower())
            return (len(shared), ratio)
        candidates.sort(key=_candidate_strength, reverse=True)
        logger.info(
            f"  Deep semantic dedup: trimming {len(candidates)} → {max_candidates} candidate pairs (strongest first)."
        )
        candidates = candidates[:max_candidates]

    logger.info(f"  Deep semantic dedup: {len(candidates)} candidate pairs to review.")

    # Build prompt with all candidate pairs in a single call
    pair_parts = []
    for i, (a, b) in enumerate(candidates):
        summary_a = a["summary"][:200] if a["summary"] else "(no summary)"
        summary_b = b["summary"][:200] if b["summary"] else "(no summary)"
        pair_parts.append(
            f'{i+1}. A: "{a["title"]}" ({a["source"]})\n'
            f'   Summary: {summary_a}\n'
            f'   B: "{b["title"]}" ({b["source"]})\n'
            f'   Summary: {summary_b}'
        )
    pairs_text = "\n\n".join(pair_parts)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": f"""You are a news deduplication assistant. For each pair below, determine if article A is about the same specific news story/event as article B. Use the titles, sources, and summaries to make your judgment.

Answer ONLY with a JSON array of pair numbers that ARE about the same story. If none match, return an empty array [].

Be strict: two articles must be about the same specific event or announcement to count. Articles about the same general topic but different events are NOT the same story.

{pairs_text}

Return ONLY a JSON array, e.g. [1, 3] or []. No other text.""",
            }],
        )

        response_text = response.content[0].text.strip()
        match_indices = json.loads(response_text)
        if not isinstance(match_indices, list):
            match_indices = []
    except Exception as e:
        logger.warning(f"  Deep semantic dedup error: {e}")
        return 0

    confirmed_pairs: list[tuple[str, str]] = []
    for idx in match_indices:
        if 1 <= idx <= len(candidates):
            a, b = candidates[idx - 1]
            confirmed_pairs.append((a["title"], b["title"]))

    if not confirmed_pairs:
        logger.info("  Deep semantic dedup: Claude found no same-story pairs.")
        return 0

    logger.info(f"  Deep semantic dedup: Claude confirmed {len(confirmed_pairs)} same-story pairs.")

    # Group confirmed pairs, preferring vendor URLs as primary
    grouped = 0
    max_row = db.conn.execute("SELECT COALESCE(MAX(group_id), 0) FROM news_items").fetchone()
    next_group_id = (max_row[0] or 0) + 1

    for title_a, title_b in confirmed_pairs:
        row_a = db.conn.execute(
            "SELECT id, group_id, url FROM news_items WHERE LOWER(title) = ?",
            (title_a.lower().strip(),),
        ).fetchone()
        row_b = db.conn.execute(
            "SELECT id, group_id, url FROM news_items WHERE LOWER(title) = ?",
            (title_b.lower().strip(),),
        ).fetchone()

        if not row_a or not row_b or row_a["id"] == row_b["id"]:
            continue

        # Already in the same group
        if row_a["group_id"] and row_a["group_id"] == row_b["group_id"]:
            continue

        # Pick a group_id: use existing if one has it, otherwise assign new
        if row_a["group_id"]:
            gid = row_a["group_id"]
        elif row_b["group_id"]:
            gid = row_b["group_id"]
        else:
            gid = next_group_id
            next_group_id += 1

        # Assign both to the group
        db.conn.execute("UPDATE news_items SET group_id = ? WHERE id = ?", (gid, row_a["id"]))
        db.conn.execute("UPDATE news_items SET group_id = ? WHERE id = ?", (gid, row_b["id"]))

        # Ensure vendor item is primary by giving it a slightly higher score
        # within the group (query_grouped sorts by score DESC)
        a_vendor = _is_vendor_url(row_a["url"])
        b_vendor = _is_vendor_url(row_b["url"])
        if b_vendor and not a_vendor:
            # Swap scores if vendor item has lower score
            scores = db.conn.execute(
                "SELECT id, score FROM news_items WHERE id IN (?, ?)",
                (row_a["id"], row_b["id"]),
            ).fetchall()
            score_map = {r["id"]: r["score"] for r in scores}
            if score_map.get(row_b["id"], 0) < score_map.get(row_a["id"], 0):
                db.conn.execute(
                    "UPDATE news_items SET score = ? WHERE id = ?",
                    (score_map[row_a["id"]], row_b["id"]),
                )
                db.conn.execute(
                    "UPDATE news_items SET score = ? WHERE id = ?",
                    (score_map[row_b["id"]], row_a["id"]),
                )
        elif a_vendor and not b_vendor:
            scores = db.conn.execute(
                "SELECT id, score FROM news_items WHERE id IN (?, ?)",
                (row_a["id"], row_b["id"]),
            ).fetchall()
            score_map = {r["id"]: r["score"] for r in scores}
            if score_map.get(row_a["id"], 0) < score_map.get(row_b["id"], 0):
                db.conn.execute(
                    "UPDATE news_items SET score = ? WHERE id = ?",
                    (score_map[row_b["id"]], row_a["id"]),
                )
                db.conn.execute(
                    "UPDATE news_items SET score = ? WHERE id = ?",
                    (score_map[row_a["id"]], row_b["id"]),
                )

        grouped += 1

    db.conn.commit()
    return grouped
