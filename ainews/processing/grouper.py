"""Group similar news items by fuzzy title matching."""

from __future__ import annotations

import json
import logging
import re

import anthropic
from rapidfuzz import fuzz

from ainews.storage.database import Database, is_vendor_url

logger = logging.getLogger(__name__)

# Vendor-domain handling moved to the storage layer so the grouper and the DB's
# primary-selection share one definition. Re-exported here for backward compat.
_is_vendor_url = is_vendor_url

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


def run_grouper(
    db: Database,
    threshold: int = 48,
    min_shared_words: int = 3,
    window_days: int | None = 14,
    rebuild: bool = False,
) -> int:
    """Incrementally assign group_id to recent items. Returns groups touched.

    A new (ungrouped) item joins a group when some member of that group shares
    ≥ ``min_shared_words`` significant words AND has a fuzzy title score ≥
    ``threshold``; it joins the best-matching group. Two previously-ungrouped
    items that match each other form a new group.

    Unlike the old implementation, this does NOT clear and renumber every group
    on each run. Existing ``group_id`` values are preserved (stable across runs)
    and only items currently without a group are considered for assignment. Work
    is scoped to items published within the last ``window_days`` so the cost
    does not grow with total history — pass ``window_days=None`` to consider all
    items. Set ``rebuild=True`` to clear every group first and regroup from
    scratch (used by the backfill script).

    The lead item of each touched group is flagged via ``is_primary`` (vendor
    source preferred, then score, then earliest published).
    """
    if rebuild:
        db.clear_all_groups()

    items = db.get_recent_items_for_grouping(window_days)
    if not items:
        return 0

    item_word_cache: dict[int, set[str]] = {}

    def words_of(it: dict) -> set[str]:
        cached = item_word_cache.get(it["id"])
        if cached is None:
            cached = _significant_words(it["title"].lower().strip())
            item_word_cache[it["id"]] = cached
        return cached

    # Seed clusters from groups that already exist; collect the rest as
    # candidates for assignment. Existing members keep their group_id.
    clusters: list[dict] = []
    by_gid: dict[int, dict] = {}
    ungrouped: list[dict] = []
    for it in items:
        gid = it["group_id"]
        if gid is not None:
            cl = by_gid.get(gid)
            if cl is None:
                cl = {"gid": gid, "members": []}
                by_gid[gid] = cl
                clusters.append(cl)
            cl["members"].append(it)
        else:
            ungrouped.append(it)

    next_gid = db.max_group_id() + 1
    newly_assigned: dict[int, int] = {}  # item_id -> gid, to persist
    affected_gids: set[int] = set()

    for item in ungrouped:
        item_words = words_of(item)
        if len(item_words) < min_shared_words:
            continue  # title too thin to match; stays ungrouped

        title_lower = item["title"].lower().strip()
        best_cluster: dict | None = None
        best_score = -1
        for cl in clusters:
            for member in cl["members"]:
                if len(item_words & words_of(member)) < min_shared_words:
                    continue
                score = fuzz.token_sort_ratio(
                    title_lower, member["title"].lower().strip()
                )
                if score >= threshold and score > best_score:
                    best_cluster = cl
                    best_score = score
                    break  # this cluster matches; move on to compare others

        if best_cluster is None:
            # No match — open a new singleton cluster (no gid until it grows).
            clusters.append({"gid": None, "members": [item]})
            continue

        if best_cluster["gid"] is None:
            # First pairing of two previously-ungrouped items: mint a gid and
            # persist the seed member too.
            best_cluster["gid"] = next_gid
            next_gid += 1
            for m in best_cluster["members"]:
                newly_assigned[m["id"]] = best_cluster["gid"]
        gid = best_cluster["gid"]
        best_cluster["members"].append(item)
        newly_assigned[item["id"]] = gid
        affected_gids.add(gid)

    for item_id, gid in newly_assigned.items():
        db.set_group(item_id, gid)
    db.commit()

    for gid in affected_gids:
        db.recompute_group_primary(gid)

    return len(affected_gids)


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

    # Batch candidates to keep each Claude call bounded — a single 1000-pair
    # call regularly truncates output or returns empty. ~150 pairs per call
    # comfortably fits in max_tokens=4096 for the JSON-array response.
    BATCH_SIZE = 150
    match_indices: list[int] = []
    for batch_start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[batch_start : batch_start + BATCH_SIZE]
        pair_parts = []
        for j, (a, b) in enumerate(batch):
            summary_a = a["summary"][:200] if a["summary"] else "(no summary)"
            summary_b = b["summary"][:200] if b["summary"] else "(no summary)"
            # Index within the BATCH (1-based); we remap to global below.
            pair_parts.append(
                f'{j+1}. A: "{a["title"]}" ({a["source"]})\n'
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
            response_text = (response.content[0].text or "").strip()
            if not response_text:
                logger.warning(
                    "  Deep semantic dedup: empty response on batch %d-%d",
                    batch_start, batch_start + len(batch),
                )
                continue
            # Strip markdown fences if present
            stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", response_text).strip()
            # Find the outermost JSON array (handles both flat [1,2,3] and
            # cluster-of-clusters [[1,2],[3,4]] schemas the model sometimes
            # returns despite the instruction).
            m = re.search(r"\[[\s\S]*\]", stripped)
            payload = m.group(0) if m else stripped
            batch_data = json.loads(payload)
            # Normalise to a flat list of integers. Cluster schema means each
            # sub-list is a set of indices to be merged — every index in it
            # is part of a confirmed-same-story group, so all of them count.
            flat: list[int] = []
            if isinstance(batch_data, list):
                for entry in batch_data:
                    if isinstance(entry, int):
                        flat.append(entry)
                    elif isinstance(entry, list):
                        for k in entry:
                            if isinstance(k, int):
                                flat.append(k)
            # Remap batch-relative 1-based indices to global positions.
            for k in flat:
                if 1 <= k <= len(batch):
                    match_indices.append(batch_start + k)
        except Exception as e:
            logger.warning(
                "  Deep semantic dedup error on batch %d-%d: %s (resp head: %r)",
                batch_start, batch_start + len(batch), e,
                (response_text[:120] if 'response_text' in dir() else 'no-response'),
            )
            continue

    confirmed_pairs: list[tuple[str, str]] = []
    for idx in match_indices:
        if 1 <= idx <= len(candidates):
            a, b = candidates[idx - 1]
            confirmed_pairs.append((a["title"], b["title"]))

    if not confirmed_pairs:
        logger.info("  Deep semantic dedup: Claude found no same-story pairs.")
        return 0

    logger.info(f"  Deep semantic dedup: Claude confirmed {len(confirmed_pairs)} same-story pairs.")

    # Group confirmed pairs. The lead item is chosen afterwards by
    # recompute_group_primary (vendor source preferred) — we no longer mutate
    # `score` to force display order.
    grouped = 0
    next_group_id = db.max_group_id() + 1
    affected_gids: set[int] = set()

    for title_a, title_b in confirmed_pairs:
        row_a = db.conn.execute(
            "SELECT id, group_id FROM news_items WHERE LOWER(title) = ?",
            (title_a.lower().strip(),),
        ).fetchone()
        row_b = db.conn.execute(
            "SELECT id, group_id FROM news_items WHERE LOWER(title) = ?",
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

        db.conn.execute("UPDATE news_items SET group_id = ? WHERE id = ?", (gid, row_a["id"]))
        db.conn.execute("UPDATE news_items SET group_id = ? WHERE id = ?", (gid, row_b["id"]))
        affected_gids.add(gid)
        grouped += 1

    db.conn.commit()
    for gid in affected_gids:
        db.recompute_group_primary(gid)
    return grouped
