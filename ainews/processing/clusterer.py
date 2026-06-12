"""Embedding-based story clustering — the single owner of ``group_id``.

Replaces the lexical grouper + Claude pairwise dedup stack. Each item gets a
semantic vector (title + short summary, via Bedrock Titan); items are
clustered by cosine similarity against the **centroid** of each cluster,
within a hard **time window**. Both choices are structural, not tunings:

- Centroid assignment prevents single-link chaining — the failure mode that
  produced 39-member "Anthropic mega-clusters" mixing the IPO, the Fable 5
  release, and weeks of Mythos coverage. An item must resemble what the
  cluster is *about on average*, not merely its most agreeable member.
- The time cap (no member may be further than ``max_span_days`` from the
  cluster's earliest coverage) encodes what a story IS: an event and its
  coverage tail — not a months-long topic.

Same-topic-but-different-event stories sit around ~0.6-0.75 cosine on Titan
V2; same-story coverage lands ~0.8+. The default threshold separates the two
regimes; calibrate against real data when changing models.

Incremental and idempotent: existing group ids are stable; only ungrouped
items within the window are assigned. ``rebuild=True`` re-clusters from
scratch (backfill).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ainews.processing.embeddings import (
    TitanEmbedder,
    cosine,
    item_embed_text,
    mean_vector,
    pack_vector,
    unpack_vector,
)
from ainews.storage.database import Database

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.80
DEFAULT_WINDOW_DAYS = 14
DEFAULT_MAX_SPAN_DAYS = 4


def _parse_published(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def ensure_embeddings(db: Database, items: "list[dict]", embedder) -> "dict[int, list[float]]":
    """Return id -> vector for every item, embedding the ones not yet stored."""
    model = getattr(embedder, "model_id", "unknown")
    have = db.get_embeddings([it["id"] for it in items], model)
    vectors: "dict[int, list[float]]" = {
        item_id: unpack_vector(blob) for item_id, blob in have.items()
    }
    missing = [it for it in items if it["id"] not in vectors]
    if missing:
        logger.info("  [Cluster] embedding %d new items", len(missing))
    for it in missing:
        text = item_embed_text(it["title"], it.get("short_summary"), it.get("summary"))
        vec = embedder.embed(text)
        vectors[it["id"]] = vec
        db.upsert_embedding(it["id"], model, len(vec), pack_vector(vec))
    if missing:
        db.commit()
    return vectors


class _Cluster:
    __slots__ = ("gid", "member_ids", "vectors", "earliest", "latest")

    def __init__(self, gid: Optional[int]):
        self.gid = gid
        self.member_ids: "list[int]" = []
        self.vectors: "list[list[float]]" = []
        self.earliest: Optional[datetime] = None
        self.latest: Optional[datetime] = None

    def add(self, item_id: int, vec: "list[float]", published: Optional[datetime]):
        self.member_ids.append(item_id)
        self.vectors.append(vec)
        if published:
            if self.earliest is None or published < self.earliest:
                self.earliest = published
            if self.latest is None or published > self.latest:
                self.latest = published

    def centroid(self) -> "list[float]":
        return mean_vector(self.vectors)

    def within_span(self, published: Optional[datetime], max_span_days: int) -> bool:
        if published is None or self.earliest is None:
            return True  # undated rows can't be excluded on time
        span = timedelta(days=max_span_days)
        return (published - self.earliest) <= span and (self.earliest - published) <= span


def cluster_recent_items(
    db: Database,
    embedder=None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    window_days: Optional[int] = DEFAULT_WINDOW_DAYS,
    max_span_days: int = DEFAULT_MAX_SPAN_DAYS,
    rebuild: bool = False,
) -> int:
    """Assign ``group_id`` to recent items by centroid-cosine clustering.

    Returns the number of clusters touched. The lead item of every touched
    cluster is re-flagged via ``recompute_group_primary``.
    """
    if rebuild:
        db.clear_all_groups()

    items = db.get_items_for_clustering(window_days)
    if not items:
        return 0

    embedder = embedder or TitanEmbedder()
    vectors = ensure_embeddings(db, items, embedder)

    # Seed clusters from existing assignments (stable ids), then place each
    # ungrouped item — in published order, so coverage accretes onto the
    # earliest report of the event.
    clusters: "list[_Cluster]" = []
    by_gid: "dict[int, _Cluster]" = {}
    ungrouped: "list[dict]" = []
    for it in items:
        gid = it["group_id"]
        if gid is not None:
            cl = by_gid.get(gid)
            if cl is None:
                cl = _Cluster(gid)
                by_gid[gid] = cl
                clusters.append(cl)
            cl.add(it["id"], vectors[it["id"]], _parse_published(it["published"]))
        else:
            ungrouped.append(it)

    next_gid = db.max_group_id() + 1
    assignments: "dict[int, int]" = {}
    affected: "set[int]" = set()

    for it in ungrouped:
        vec = vectors[it["id"]]
        published = _parse_published(it["published"])

        best: Optional[_Cluster] = None
        best_sim = threshold
        for cl in clusters:
            if not cl.within_span(published, max_span_days):
                continue
            sim = cosine(vec, cl.centroid())
            if sim >= best_sim:
                best = cl
                best_sim = sim

        if best is None:
            solo = _Cluster(None)
            solo.add(it["id"], vec, published)
            clusters.append(solo)
            continue

        if best.gid is None:
            # Second item of a brand-new cluster: mint the id, persist the seed.
            best.gid = next_gid
            next_gid += 1
            for member_id in best.member_ids:
                assignments[member_id] = best.gid
        best.add(it["id"], vec, published)
        assignments[it["id"]] = best.gid
        affected.add(best.gid)

    for item_id, gid in assignments.items():
        db.set_group(item_id, gid)
    db.commit()

    for gid in affected:
        db.recompute_group_primary(gid)

    if affected:
        logger.info("  [Cluster] %d clusters touched (%d items assigned)",
                    len(affected), len(assignments))
    return len(affected)
