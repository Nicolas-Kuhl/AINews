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

# Two-stage dedup: pairs whose cosine lands in [BORDERLINE_LOW, threshold) are
# "maybe the same story" — too loose to auto-merge, too close to ignore. A
# cheap LLM call decides each. Below BORDERLINE_LOW they're left apart; same-
# story coverage with divergent framing sits ~0.45-0.65, while genuinely
# different events on a shared topic sit ~0.38-0.42, so the floor separates
# the regimes before the LLM ever sees a pair.
BORDERLINE_LOW = 0.45
# Only judge pairs where at least one side has coverage this recent — don't
# re-litigate old, settled clusters every run.
BORDERLINE_RECENT_DAYS = 4
MAX_BORDERLINE_PAIRS = 60
_JUDGE_BATCH = 30


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


def _cluster_repr_text(cluster: "_Cluster", items_by_id: dict) -> str:
    """Representative text for a cluster: its highest-scored member's
    title + short summary — what an editor would skim to judge the story."""
    best_id = max(cluster.member_ids, key=lambda i: items_by_id[i].get("score", 0))
    it = items_by_id[best_id]
    body = (it.get("short_summary") or "").strip() or (it.get("summary") or "").strip()
    return f"{it['title']}\n{body[:300]}" if body else it["title"]


def _is_recent(cluster: "_Cluster", now: datetime, days: int) -> bool:
    return cluster.latest is not None and (now - cluster.latest) <= timedelta(days=days)


def _borderline_pairs(
    clusters: "list[_Cluster]",
    *,
    low: float,
    high: float,
    max_span_days: int,
    now: datetime,
    recent_days: int,
    max_pairs: int,
) -> "list[tuple[int, int]]":
    """Cluster index pairs whose centroids are 'maybe same story' and worth a
    judgement call: cosine in [low, high), time-compatible, at least one recent."""
    scored: "list[tuple[float, int, int]]" = []
    for i in range(len(clusters)):
        a = clusters[i]
        for j in range(i + 1, len(clusters)):
            b = clusters[j]
            if not (_is_recent(a, now, recent_days) or _is_recent(b, now, recent_days)):
                continue
            # Time-compatible: their coverage windows are within max_span_days.
            if a.earliest and b.earliest:
                gap = abs((a.earliest - b.earliest).days)
                if gap > max_span_days:
                    continue
            sim = cosine(a.centroid(), b.centroid())
            if low <= sim < high:
                scored.append((sim, i, j))
    scored.sort(reverse=True)  # strongest candidates first under the cap
    return [(i, j) for _sim, i, j in scored[:max_pairs]]


def make_llm_judge(client, model: str):
    """Build a judge(pairs)->list[bool] backed by Claude. Each pair is
    (repr_a, repr_b); returns True where the two describe the same news event."""
    def judge(pairs: "list[tuple[str, str]]") -> "list[bool]":
        out = [False] * len(pairs)
        for start in range(0, len(pairs), _JUDGE_BATCH):
            batch = pairs[start:start + _JUDGE_BATCH]
            listing = "\n\n".join(
                f'{k}. A: "{a}"\n   B: "{b}"' for k, (a, b) in enumerate(batch, 1)
            )
            prompt = (
                "You are a news editor deduplicating coverage. For each numbered "
                "pair, decide if A and B report the SAME specific news event "
                "(same announcement/action/incident), not merely the same topic "
                "or company. Different events about the same subject are NOT the "
                "same story.\n\n"
                "Return ONLY a JSON array of the numbers that ARE the same event, "
                "e.g. [1, 4]. Empty array [] if none.\n\n" + listing
            )
            try:
                resp = client.messages.create(
                    model=model, max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}],
                )
                from ainews.processing.deduplicator import parse_first_json_array
                arr = parse_first_json_array(resp.content[0].text or "[]")
                for n in arr:
                    if isinstance(n, int) and 1 <= n <= len(batch):
                        out[start + n - 1] = True
            except Exception as exc:  # noqa: BLE001 — borderline merges are a bonus
                logger.warning("  [Cluster] borderline judge batch failed: %s", exc)
        return out
    return judge


def _apply_merges(
    db: Database,
    clusters: "list[_Cluster]",
    merge_pairs: "list[tuple[int, int]]",
    next_gid: int,
) -> "set[int]":
    """Union the given cluster-index pairs, persist group_ids, return touched gids."""
    parent = list(range(len(clusters)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in merge_pairs:
        parent[find(i)] = find(j)

    comp_members: "dict[int, list[int]]" = {}
    comp_gid: "dict[int, Optional[int]]" = {}
    for idx, cl in enumerate(clusters):
        root = find(idx)
        comp_members.setdefault(root, []).extend(cl.member_ids)
        if cl.gid is not None and comp_gid.get(root) is None:
            comp_gid[root] = cl.gid

    touched: "set[int]" = set()
    for root, member_ids in comp_members.items():
        # Only components that actually merged something (multi-cluster) matter.
        roots_clusters = [c for k, c in enumerate(clusters) if find(k) == root]
        if len(roots_clusters) < 2:
            continue
        gid = comp_gid.get(root)
        if gid is None:
            gid = next_gid
            next_gid += 1
        for mid in member_ids:
            db.set_group(mid, gid)
        touched.add(gid)
    if touched:
        db.commit()
    return touched


def cluster_recent_items(
    db: Database,
    embedder=None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    window_days: Optional[int] = DEFAULT_WINDOW_DAYS,
    max_span_days: int = DEFAULT_MAX_SPAN_DAYS,
    rebuild: bool = False,
    borderline_low: float = BORDERLINE_LOW,
    judge=None,
    now: Optional[datetime] = None,
) -> int:
    """Assign ``group_id`` to recent items by centroid-cosine clustering.

    Stage 1 auto-merges items whose cosine to a cluster centroid is >=
    ``threshold``. Stage 2 (optional) hands borderline pairs — cosine in
    [``borderline_low``, ``threshold``) — to ``judge`` (an LLM in production)
    which decides same-event vs different-event; confirmed pairs merge. Pass
    ``judge=None`` to skip stage 2 (pure embeddings).

    Returns the number of clusters touched. The lead item of every touched
    cluster is re-flagged via ``recompute_group_primary``.
    """
    now = now or datetime.now(timezone.utc)
    if rebuild:
        db.clear_all_groups()

    items = db.get_items_for_clustering(window_days)
    if not items:
        return 0
    items_by_id = {it["id"]: it for it in items}

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

    # Stage 2: LLM-judged borderline merges. Operates on the post-stage-1
    # clusters (singletons that never matched are 1-member clusters here).
    if judge is not None:
        pairs = _borderline_pairs(
            clusters, low=borderline_low, high=threshold,
            max_span_days=max_span_days, now=now,
            recent_days=BORDERLINE_RECENT_DAYS, max_pairs=MAX_BORDERLINE_PAIRS,
        )
        if pairs:
            texts = [
                (_cluster_repr_text(clusters[i], items_by_id),
                 _cluster_repr_text(clusters[j], items_by_id))
                for i, j in pairs
            ]
            verdicts = judge(texts)
            confirmed = [pairs[k] for k, ok in enumerate(verdicts) if ok]
            logger.info("  [Cluster] borderline: %d candidate pairs, %d confirmed same-event",
                        len(pairs), len(confirmed))
            if confirmed:
                merged_gids = _apply_merges(db, clusters, confirmed, db.max_group_id() + 1)
                affected |= merged_gids

    for gid in affected:
        db.recompute_group_primary(gid)

    if affected:
        logger.info("  [Cluster] %d clusters touched (%d items assigned)",
                    len(affected), len(assignments))
    return len(affected)
